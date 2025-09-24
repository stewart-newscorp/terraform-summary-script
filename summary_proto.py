# uses the protobuf terraform to read terraform plans, and generate a summary...a
# it takes a lot longer to generate json files with terraform show -json
# plan file is here: https://github.com/hashicorp/terraform/blob/main/internal/plans/planproto/planfile.proto
# you are not strictly meant to use it but it is a lot faster than using the json files
# you can see how terraform reads the protobuf file here: https://github.com/hashicorp/terraform/blob/main/internal/plans/planfile/tfplan.go
#     "account": account_path,

import logging
import sys
import zipfile
from pathlib import Path

import planfile_pb2

logging.basicConfig(encoding="utf-8", level=logging.INFO)
logger = logging.getLogger(__name__)

plan = planfile_pb2.Plan()


def record_changes(account_summary: dict, resource_changes: list[planfile_pb2.ResourceInstanceChange]):
    for resource in resource_changes:
        handle_action(resource.change.action, account_summary)


def warn_if_drift_changes(account_marker: str, resource_changes: list[planfile_pb2.ResourceInstanceChange]):
    drift_summary = {
        "account": account_marker,
        "create": 0,
        "update": 0,
        "delete": 0,
    }
    for resource in resource_changes:
        handle_action(resource.change.action, drift_summary)
        if drift_summary["create"] > 0 or drift_summary["update"] > 0 or drift_summary["delete"] > 0:
            logger.warning(f"{account_marker} had drift, might not result in change")
            drift_summary = {
                "account": account_marker,
                "create": 0,
                "update": 0,
                "delete": 0,
            }


def handle_action(action, account_summary: dict):
    match action:
        case planfile_pb2.Action.NOOP:
            return
        case planfile_pb2.Action.CREATE:
            account_summary["create"] += 1
            return
        case planfile_pb2.Action.UPDATE:
            account_summary["update"] += 1
            return
        case planfile_pb2.Action.DELETE:
            account_summary["delete"] += 1
            return
        case planfile_pb2.Action.DELETE_THEN_CREATE:
            account_summary["delete"] += 1
            return
        case planfile_pb2.Action.CREATE_THEN_DELETE:
            logger.warning("CREATE_THEN_DELETE action encountered, this is not supported in the summary.")
            account_summary["delete"] += 1
            return
        case _:  # default case
            logger.error(f"Unknown action: {action}")
            sys.exit(1)


def find_tfplan(dir: str = "accounts", file_name: str = "tfplan.out") -> list[dict]:
    accounts_summary = []
    if not Path(f"./{dir}").is_dir():
        logger.error(f"Directory {dir} does not exist, not in base of repository. Exiting.")
        sys.exit(1)
    logger.info(f"Looking for plan files in ./{dir} directory")

    for business_unit_dir in Path(f"./{dir}").iterdir():
        if business_unit_dir.is_dir():
            for account_dir in business_unit_dir.iterdir():
                if account_dir.is_dir():
                    plan_files = list(account_dir.rglob(file_name))
                    if len(plan_files) > 1:
                        logger.error("More plan_files than one in account... exiting")
                        sys.exit(1)
                    if len(plan_files) == 1:
                        accounts_summary.append(read_plan_file(plan_files[0], f"{business_unit_dir.name}/{account_dir.name}"))
    return accounts_summary


class Colours:
    # ANSI colour codes
    RED = "\033[31m"  # Error
    GREEN = "\033[32m"  # Info/Success
    YELLOW = "\033[33m"  # Warning
    BLUE = "\033[34m"  # Info (alternative)
    RESET = "\033[0m"  # Reset to default


def coloured_str(message, colour) -> str:
    return f"{colour}{message}{Colours.RESET}"


def colour_if_not_zero(value: int, colour: str) -> str:
    if value > 0:
        return f"{coloured_str(str(value), colour):<20}"  # 10 characters in anscii escapes
    return f"{str(value):<10}"


def pretty_print_summary(summary: list[dict]):
    summary_markdown = f"|{'Account':<50}|{'Add':<10}|{'Change':<10}|{'Destroy':<10}|\n"
    summary_markdown += f"|{('-' * 5)}|{('-' * 5)}|{('-' * 5)}|{('-' * 5)}|\n"
    for item in summary:
        summary_markdown += f"|{item['account']:<50}|{item['create']:<10}|{item['update']:<10}|{item['delete']:<10}|\n"

    summary_text_coloured = f"{'Account':<50} {'Add':<10} {'Change':<10} {'Destroy':<10}\n"
    summary_text_coloured += coloured_str(("-" * 80), Colours.BLUE)
    summary_text_coloured += "\n"
    for item in summary:
        account = f"{item['account']:<50}"
        create = colour_if_not_zero(item["create"], Colours.GREEN)
        update = colour_if_not_zero(item["update"], Colours.YELLOW)
        delete = colour_if_not_zero(item["delete"], Colours.RED)
        summary_text_coloured += f"{account} {create} {update} {delete}\n"
    return summary_markdown, summary_text_coloured


def read_plan_file(zip_path: str, account_marker: str):
    try:
        # plan output is a zip file
        with zipfile.ZipFile(zip_path, "r") as zip_file:
            # multiple files are stored in the zip file, after 'tfplan'
            with zip_file.open("tfplan") as f:
                plan_data = f.read()
                plan.ParseFromString(plan_data)
    except zipfile.BadZipFile:
        logger.error("The file is not a valid ZIP file.")
        sys.exit(1)

    if plan.version != 3:
        logger.error(f"Unsupported plan version {plan.version}. Expected version 3.")
        sys.exit(1)

    if len(plan.deferred_changes) > 0:
        logger.error("deferred changes found in the plan. Don't know what to do. Exiting.")
        sys.exit(1)

    change_summary = {
        "account": account_marker,
        "create": 0,
        "update": 0,
        "delete": 0,
    }

    record_changes(change_summary, plan.resource_changes)
    warn_if_drift_changes(account_marker, plan.resource_drift)
    return change_summary


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        logger.error("This script requires Python 3.10 or higher.")
        sys.exit(1)
    if len(sys.argv) < 2:
        logger.error(f"Usage: python {sys.argv[0]} plan_file")
        sys.exit(1)
    logger.info(f"Running {sys.argv[0]}")
    plan_file = sys.argv[1]
    logger.info(f"Reading plan file: {plan_file}")
    summary = find_tfplan("accounts", plan_file)
    summary = sorted(summary, key=lambda x: (-x["delete"], -x["update"], -x["create"], x["account"]))
    summary_text, summary_text_coloured = pretty_print_summary(summary)
    print(summary_text_coloured)
    if len(summary) == 0:
        logger.info("No accounts planned")
    else:
        with open("summary.md", "w") as file:
            file.write(summary_text)
