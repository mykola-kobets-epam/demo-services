#!/usr/bin/env python3
"""Print the Aos service instance identity from environment variables on start."""

import os
import sys
import time
from datetime import datetime

LOG_INTERVAL = 5


def now() -> str:
    return datetime.now().strftime("%b %d %H:%M:%S.%f")

ENV_VARS = {
    "AOS_ITEM_ID": "item ID",
    "AOS_SUBJECT_ID": "subject ID",
    "AOS_INSTANCE_INDEX": "instance index",
    "AOS_INSTANCE_ID": "instance ID",
    "AOS_SECRET": "secret",
}


def get_instance_ident() -> str:
    values = {name: os.environ.get(name) for name in ENV_VARS}

    for name, label in ENV_VARS.items():
        value = values[name]

    ident = (
        f"service:0:"
        f"{values['AOS_ITEM_ID']}:"
        f"{values['AOS_SUBJECT_ID']}:"
        f"{values['AOS_INSTANCE_INDEX']}"
    )

    return f"{{{ident}}}"


if __name__ == "__main__":
    ident = get_instance_ident()
    instance_id = os.environ.get("AOS_INSTANCE_ID", "<not set>")

    print(f"Instance started with ident: {ident} instance id: {instance_id} time: {now()}")
    sys.stdout.flush()

    iteration = 0
    while True:
        iteration += 1
        print(f"Instance {ident} is running (iteration {iteration}) {now()}")
        sys.stdout.flush()
        time.sleep(LOG_INTERVAL)
