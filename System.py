from datetime import datetime
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time
from decimal import Decimal, InvalidOperation
from typing import List


BANNER = "NYXOS 2026"
BOOT_MESSAGES = (
    "INITIALIZING NYXOS 2026",
    "CHECKING MEMORY ........ OK",
    "LOADING SYSTEM SERVICES .. OK",
    "STARTING TERMINAL SESSION . OK",
)
LOGIN_SCREEN = "NYXOS TSO LOGON"
HELP_LINES = (
    "COMMANDS",
    "  help                         SHOW THIS LIST",
    "  whoami                       SHOW CURRENT USER",
    "  en                           ENABLE ROOT ACCESS",
    "  shutdown                     SHUT DOWN NYXOS (ROOT)",
    "  clearterm                    CLEAR THE TERMINAL",
    "  date                         SHOW THE HOST DATE",
    "  time                         SHOW THE HOST TIME",
    "  uptime                       SHOW NYXOS UPTIME",
    "  hostname                     SHOW THE HOSTNAME",
    "  resolve HOST                 RESOLVE A HOSTNAME",
    "  ping HOST                    PING THROUGH THE HOST",
    "  dataset list                 LIST DATASETS",
    "  dataset view NAME            VIEW A DATASET",
    "  dataset edit NAME            EDIT A DATASET",
    "  dataset delete NAME         DELETE A DATASET",
    "  dataset rename OLD NEW      RENAME A DATASET",
    "  compile dataset NAME         COMPILE MATH DATASET",
)
USER_TABLE = {
    "user": "user",
}
ROOT_PASSWORD = "root"
FS_IMAGE_PATH = Path(__file__).with_name("fs.fs")
UPTIME_START = time.monotonic()


def load_filesystem() -> None:
    if not FS_IMAGE_PATH.exists():
        return
    try:
        image = json.loads(FS_IMAGE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    datasets = image.get("datasets")
    if isinstance(datasets, dict):
        DATASETS.clear()
        DATASETS.update(datasets)


def save_filesystem() -> None:
    image = {"datasets": DATASETS}
    FS_IMAGE_PATH.write_text(
        json.dumps(image, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
DATASETS = {
    "system": {
        "name": "NYXOS",
        "version": "2026",
        "status": "online",
    },
}
MATH_EXPRESSION = re.compile(
    r"^\s*(-?(?:\d+(?:\.\d*)?|\.\d+))\s*([+/*-])\s*"
    r"(-?(?:\d+(?:\.\d*)?|\.\d+))\s*$"
)


def print_with_buffer(text: str, delay: float = 0.018) -> None:
    for character in text:
        sys.stdout.write(character)
        sys.stdout.flush()
        time.sleep(delay)


def print_line(text: str, delay: float = 0.018) -> None:
    print_with_buffer(text, delay)
    sys.stdout.write("\n")
    sys.stdout.flush()


def clear_terminal() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def run_boot_sequence(character_delay: float = 0.018, line_delay: float = 0.25) -> None:
    print_line(BANNER, character_delay)
    for message in BOOT_MESSAGES:
        time.sleep(line_delay)
        print_line(message, character_delay)


def login(input_func=input, password_func=getpass.getpass) -> str:
    while True:
        username = input_func("ENTER USERID ===> ")
        password = password_func("ENTER PASSWORD => ")
        if USER_TABLE.get(username) == password:
            return username
        print_line("INVALID LOGON")


def show_dataset(name: str) -> None:
    dataset = DATASETS.get(name)
    if dataset is None:
        print_line("DATASET NOT FOUND")
        return
    print_line(f"DATASET: {name}")
    for key, value in dataset.items():
        print_line(f"{key} = {value}")


def edit_dataset(name: str, input_func=input) -> None:
    dataset = DATASETS.setdefault(name, {})
    print_line(f"EDITING DATASET: {name}")
    print_line("TYPE key=value, or SAVE to finish")
    while True:
        entry = input_func("DATASET EDIT> ").strip()
        if entry.lower() == "save":
            save_filesystem()
            print_line("DATASET SAVED")
            return
        if "=" not in entry:
            if compile_expression(entry) is not None:
                index = 1
                while str(index) in dataset:
                    index += 1
                dataset[str(index)] = entry
                print_line(f"ADDED {index}: {entry}")
                continue
            print_line("USE key=value OR SAVE")
            continue
        key, value = entry.split("=", 1)
        dataset[key.strip()] = value.strip()


def compile_expression(expression: str):
    match = MATH_EXPRESSION.fullmatch(expression)
    if match is None:
        return None

    try:
        left = Decimal(match.group(1))
        right = Decimal(match.group(3))
        operator = match.group(2)
        if operator == "+":
            return left + right
        if operator == "-":
            return left - right
        if operator == "*":
            return left * right
        if right == 0:
            return "DIVISION BY ZERO"
        return left / right
    except InvalidOperation:
        return None


def compile_dataset(name: str) -> None:
    dataset = DATASETS.get(name)
    if dataset is None:
        print_line("DATASET NOT FOUND")
        return

    compiled = False
    for key, value in dataset.items():
        if not isinstance(value, str):
            continue
        result = compile_expression(value)
        if result is None:
            continue
        print_line(f"{key}: {value} = {result}")
        compiled = True
    if not compiled:
        print_line("NO COMPILABLE MATH")


def handle_dataset(command_parts: List[str], input_func=input) -> None:
    action = command_parts[1].lower() if len(command_parts) > 1 else "list"
    if action == "list":
        for name in DATASETS:
            print_line(name)
    elif action == "view" and len(command_parts) > 2:
        show_dataset(command_parts[2])
    elif action == "edit" and len(command_parts) > 2:
        edit_dataset(command_parts[2], input_func)
    elif action == "delete" and len(command_parts) > 2:
        name = command_parts[2]
        if name not in DATASETS:
            print_line("DATASET NOT FOUND")
        else:
            del DATASETS[name]
            save_filesystem()
            print_line(f"DATASET DELETED: {name}")
    elif action == "rename" and len(command_parts) > 3:
        old_name, new_name = command_parts[2:4]
        if old_name not in DATASETS:
            print_line("DATASET NOT FOUND")
        elif new_name in DATASETS:
            print_line("DATASET ALREADY EXISTS")
        else:
            DATASETS[new_name] = DATASETS.pop(old_name)
            save_filesystem()
            print_line(f"DATASET RENAMED: {old_name} -> {new_name}")
    else:
        print_line(
            "USAGE: dataset list | view NAME | edit NAME | "
            "delete NAME | rename OLD NEW"
        )


def show_uptime() -> None:
    elapsed = int(time.monotonic() - UPTIME_START)
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)
    print_line(f"UPTIME: {hours:02d}:{minutes:02d}:{seconds:02d}")


def handle_network(command_parts: List[str]) -> None:
    command_name = command_parts[0].lower()
    if command_name == "hostname":
        print_line(socket.gethostname())
        return
    if len(command_parts) < 2:
        print_line(f"USAGE: {command_name} HOST")
        return

    target = command_parts[1]
    if command_name == "resolve":
        try:
            print_line(f"{target} -> {socket.gethostbyname(target)}")
        except socket.gaierror:
            print_line("HOST NOT FOUND")
    elif command_name == "ping":
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "2000", target],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            print_line("PING FAILED")
            return
        if result.returncode == 0:
            print_line(f"PING {target}: OK")
        else:
            print_line(f"PING {target}: FAILED")


def show_help() -> None:
    for line in HELP_LINES:
        print_line(line)


def command_loop(
    input_func=input,
    password_func=getpass.getpass,
    username="user",
    clear_func=clear_terminal,
) -> None:
    is_root = False
    while True:
        prompt = "# " if is_root else "> "
        command = input_func(prompt).strip()
        command_parts = shlex.split(command)
        if not command_parts:
            continue

        command_name = command_parts[0].lower()
        if command_name == "help":
            show_help()
        elif command_name == "clearterm":
            clear_func()
        elif command_name == "date":
            print_line(datetime.now().strftime("%Y-%m-%d"))
        elif command_name == "time":
            print_line(datetime.now().strftime("%H:%M:%S"))
        elif command_name == "uptime":
            show_uptime()
        elif command_name in ("hostname", "resolve", "ping"):
            handle_network(command_parts)
        elif command_name == "whoami":
            print_line("root" if is_root else username)
        elif command_name == "en":
            if is_root:
                print_line("ALREADY ROOT")
            elif password_func("ROOT PASSWORD => ") == ROOT_PASSWORD:
                is_root = True
                print_line("ROOT ACCESS ENABLED")
            else:
                print_line("ROOT ACCESS DENIED")
        elif command_name == "shutdown":
            if is_root:
                save_filesystem()
                print_line("SYSTEM SHUTDOWN")
                return
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        elif command_name == "dataset":
            handle_dataset(command_parts, input_func)
        elif (
            command_name == "compile"
            and len(command_parts) == 3
            and command_parts[1].lower() == "dataset"
        ):
            compile_dataset(command_parts[2])
        else:
            print_line("UNKNOWN COMMAND")


def main() -> None:
    load_filesystem()
    run_boot_sequence()
    time.sleep(0.5)
    print_line(LOGIN_SCREEN)
    username = login()
    command_loop(username=username)


if __name__ == "__main__":
    main()
