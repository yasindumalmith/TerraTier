import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

from run_remediation import validate_identifier
from validate_project_remediation import (
    MODULE_BLOCK_RE,
    RESOURCE_BLOCK_RE,
    discover_module_directories,
    discover_resources,
    iter_blocks,
    normalize_finding,
    run_checkov,
    terraform_files,
    write_json,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = PROJECT_ROOT / "pilot_samples"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "project_features"

VARIABLE_RE = re.compile(r'\bvariable\s+"([^"]+)"\s*\{')
OUTPUT_RE = re.compile(r'\boutput\s+"([^"]+)"\s*\{')
LOCALS_RE = re.compile(r"\blocals\s*\{")
ASSIGNMENT_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_-]*\s*=", re.MULTILINE)
DYNAMIC_RE = re.compile(r'\bdynamic\s+"[^"]+"\s*\{')
FOR_EACH_RE = re.compile(r"^\s*for_each\s*=", re.MULTILINE)
COUNT_RE = re.compile(r"^\s*count\s*=", re.MULTILINE)

CATEGORY_KEYWORDS = {
    "iam": ("iam", "policy", "privilege", "permission"),
    "network": (
        "network",
        "security_group",
        "security group",
        "subnet",
        "vpc",
        "ingress",
        "egress",
        "port",
        "publicly accessible",
    ),
    "encryption": ("encrypt", "kms", "key rotation", "plaintext"),
    "logging": ("log", "monitor", "cloudtrail", "notification", "audit"),
    "storage": ("s3", "bucket", "storage", "ebs", "efs", "snapshot"),
    "compute": ("ec2", "instance", "lambda", "ecs", "eks", "compute"),
    "database": ("database", "rds", "dynamodb", "redshift", "db_"),
}


class ProjectFeatureError(RuntimeError):
    """A clear, user-facing project feature extraction error."""


def count_lines_of_code(content: str):
    return sum(
        1
        for line in content.splitlines()
        if line.strip()
        and not line.lstrip().startswith("#")
        and not line.lstrip().startswith("//")
    )


def resource_reference_features(content: str, resources):
    references = 0
    related = set()
    for address, item in resources.items():
        base = (
            f"data.{item['resource_type']}.{item['resource_name']}"
            if item["block_type"] == "data"
            else f"{item['resource_type']}.{item['resource_name']}"
        )
        count = len(re.findall(rf"\b{re.escape(base)}\b", content))
        if count:
            references += count
            related.add(address)
    return references, len(related)


def resource_dependency_depth(sample_dir: Path, resources):
    """Approximate dependency depth using references inside resource blocks."""
    base_to_addresses = {}
    for address, item in resources.items():
        base = (
            f"data.{item['resource_type']}.{item['resource_name']}"
            if item["block_type"] == "data"
            else f"{item['resource_type']}.{item['resource_name']}"
        )
        base_to_addresses.setdefault(base, []).append(address)

    module_dirs = discover_module_directories(sample_dir)
    graph = {address: set() for address in resources}
    for tf_file in terraform_files(sample_dir):
        content = tf_file.read_text(encoding="utf-8", errors="ignore")
        module_prefix = module_dirs.get(tf_file.parent.resolve(), "")
        for match, body in iter_blocks(content, RESOURCE_BLOCK_RE):
            block_type, resource_type, resource_name = match.groups()
            base = (
                f"data.{resource_type}.{resource_name}"
                if block_type == "data"
                else f"{resource_type}.{resource_name}"
            )
            owner = f"{module_prefix}.{base}" if module_prefix else base
            if owner not in graph:
                continue
            for referenced_base, candidates in base_to_addresses.items():
                if re.search(rf"\b{re.escape(referenced_base)}\b", body):
                    same_module = [
                        candidate
                        for candidate in candidates
                        if candidate.rsplit(".", 2)[0] == owner.rsplit(".", 2)[0]
                    ]
                    graph[owner].add((same_module or candidates)[0])

    memo = {}

    def depth(node, visiting):
        if node in memo:
            return memo[node]
        if node in visiting:
            return 0
        children = graph.get(node, set())
        result = 0 if not children else 1 + max(
            depth(child, visiting | {node}) for child in children
        )
        memo[node] = result
        return result

    return max((depth(node, set()) for node in graph), default=0)


def finding_category(finding):
    normalized = normalize_finding(finding)
    text = " ".join(
        str(normalized.get(field) or "")
        for field in ("check_id", "check_name", "resource")
    ).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "other"


def extract_features(sample_dir: Path, findings):
    files = terraform_files(sample_dir)
    contents = [path.read_text(encoding="utf-8", errors="ignore") for path in files]
    complete_content = "\n".join(contents)
    resources = discover_resources(sample_dir)
    references, related = resource_reference_features(complete_content, resources)
    category_counts = {category: 0 for category in (*CATEGORY_KEYWORDS, "other")}
    for finding in findings:
        category_counts[finding_category(finding)] += 1

    severities = [
        str(item.get("severity")).lower()
        for item in findings
        if item.get("severity") is not None
    ]
    locals_count = sum(
        len(ASSIGNMENT_RE.findall(body))
        for content in contents
        for _, body in iter_blocks(content, LOCALS_RE)
    )
    return {
        "sample_id": sample_dir.name,
        "total_lines_of_code": sum(count_lines_of_code(content) for content in contents),
        "num_tf_files": len(files),
        "total_resources": len(resources),
        "num_resource_types": len(
            {item["resource_type"] for item in resources.values()}
        ),
        "num_variables": len(VARIABLE_RE.findall(complete_content)),
        "num_outputs": len(OUTPUT_RE.findall(complete_content)),
        "num_locals": locals_count,
        "num_modules": len(MODULE_BLOCK_RE.findall(complete_content)),
        "num_resource_references": references,
        "num_related_resources": related,
        "max_dependency_depth": resource_dependency_depth(sample_dir, resources),
        "uses_module": int(bool(MODULE_BLOCK_RE.search(complete_content))),
        "uses_for_each": int(bool(FOR_EACH_RE.search(complete_content))),
        "uses_count": int(bool(COUNT_RE.search(complete_content))),
        "uses_dynamic_block": int(bool(DYNAMIC_RE.search(complete_content))),
        "total_checkov_findings": len(findings),
        "num_unique_check_ids": len(
            {item.get("check_id") for item in findings if item.get("check_id")}
        ),
        "num_affected_resources": len(
            {
                normalize_finding(item)["resource"]
                for item in findings
                if normalize_finding(item)["resource"]
            }
        ),
        "num_iam_findings": category_counts["iam"],
        "num_network_findings": category_counts["network"],
        "num_encryption_findings": category_counts["encryption"],
        "num_logging_findings": category_counts["logging"],
        "num_storage_findings": category_counts["storage"],
        "num_compute_findings": category_counts["compute"],
        "num_database_findings": category_counts["database"],
        "num_other_findings": category_counts["other"],
        "num_high_findings": severities.count("high") if severities else None,
        "num_medium_findings": severities.count("medium") if severities else None,
        "num_low_findings": severities.count("low") if severities else None,
    }


def scan_sample(sample_dir: Path):
    scan = run_checkov(sample_dir)
    if not scan["success"]:
        raise ProjectFeatureError(
            f"Checkov scan failed for {sample_dir.name}: {scan['error']}"
        )
    return extract_features(sample_dir, scan["findings"])


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract pre-LLM whole-project Terraform and Checkov features."
    )
    parser.add_argument("--sample-id", default=None)
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if importlib.util.find_spec("checkov") is None:
            raise ProjectFeatureError("Checkov is not installed in the active Python environment.")
        if args.sample_id:
            validate_identifier(args.sample_id, "--sample-id")
            sample_dirs = [SAMPLES_DIR / args.sample_id]
        else:
            sample_dirs = sorted(path for path in SAMPLES_DIR.iterdir() if path.is_dir())
        for sample_dir in sample_dirs:
            if not sample_dir.is_dir():
                raise ProjectFeatureError(f"Sample directory does not exist: {sample_dir}")

        features = []
        for sample_dir in sample_dirs:
            print(f"Scanning {sample_dir.name}...", file=sys.stderr)
            features.append(scan_sample(sample_dir))

        if args.output:
            output_file = Path(args.output).resolve()
        elif args.sample_id:
            output_file = DEFAULT_OUTPUT_DIR / f"{args.sample_id}.json"
        else:
            output_file = PROJECT_ROOT / "data" / "processed" / "project_features.json"
        payload = features[0] if args.sample_id else features
        write_json(output_file, payload)
        print(json.dumps(payload, indent=2))
        print(f"Saved features: {output_file}", file=sys.stderr)
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("ERROR: Project feature extraction interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
