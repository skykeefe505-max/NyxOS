import ast
import copy
from datetime import datetime
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import readline
import select
import shlex
import socket
import socketserver
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import List


BANNER = "NYXOS 2026"
BOOT_MESSAGES = [
    "INITIALIZING NYXOS 2026",
    "CHECKING MEMORY ........ OK",
    "LOADING SYSTEM SERVICES .. OK",
    "STARTING TERMINAL SESSION . OK",
]
LOGIN_SCREEN = "NYXOS TSO LOGON"
HELP_LINES = (
    "COMMANDS",
    "  help                         SHOW THIS LIST",
    "  whoami                       SHOW CURRENT USER",
    "  en                           ENABLE ROOT ACCESS",
    "  shutdown                     SHUT DOWN NYXOS (ROOT)",
    "  clearterm                    CLEAR THE TERMINAL",
    "  clear                        ALIAS FOR CLEARTERM",
    "  date                         SHOW THE HOST DATE",
    "  time                         SHOW THE HOST TIME",
    "  uptime                       SHOW NYXOS UPTIME",
    "  hostname                     SHOW THE HOSTNAME",
    "  resolve HOST                 RESOLVE A HOSTNAME",
    "  ping HOST                    PING THROUGH THE HOST",
    "  color on|off                 TOGGLE RETRO COLORS",
    "  errors                       SHOW ERROR LOG",
    "  audit                       SHOW AUDIT LOG (ROOT)",
    "  history                      SHOW COMMAND HISTORY",
    "  man COMMAND                  SHOW COMMAND HELP",
    "  logout                       RETURN TO LOGIN",
    "  system info                 SHOW SYSTEM INFORMATION",
    "  adduser NAME                 ADD A USER (ROOT)",
    "  deluser NAME                 DELETE A USER (ROOT)",
    "  dataset list                 LIST DATASETS",
    "  dataset view NAME            VIEW A DATASET",
    "  dataset edit NAME            EDIT A DATASET",
    "  dataset delete NAME         DELETE A DATASET",
    "  dataset rename OLD NEW      RENAME A DATASET",
    "  dataset search TEXT         SEARCH DATASETS",
    "  dataset export NAME PATH    EXPORT A DATASET",
    "  dataset import NAME PATH    IMPORT A DATASET",
    "  dataset rollback NAME       RESTORE DATASET VERSION (ROOT)",
    "  compile dataset NAME         COMPILE MATH DATASET",
    "  bootmsg list                 LIST BOOT MESSAGES",
    "  bootmsg add TEXT             ADD A BOOT MESSAGE (ROOT)",
    "  bootmsg clear                RESET BOOT MESSAGES (ROOT)",
    "  settings                     SHOW STARTUP SETTINGS",
    "  settings set KEY VALUE       SET STARTUP SETTING (ROOT)",
    "  sql start                    START LOCAL SQL SERVER (ROOT)",
    "  sql stop                     STOP LOCAL SQL SERVER (ROOT)",
    "  sql status                   SHOW SQL SERVER STATUS",
    "  sql reconnect                RECONNECT SQL SERVER",
    "  sql tables                   LIST SQL TABLES",
    "  sql query \"SQL\"              RUN SQL AS CLIENT",
    "  sql prompt                   INTERACTIVE SQL CLIENT",
        "  sql schema TABLE             SHOW TABLE SCHEMA",
    "  sql history                  SHOW SQL QUERY HISTORY",
    "  sql backup list              LIST SQL BACKUPS",
    "  sql dump PATH                BACK UP SQL DATABASE (ROOT)",
    "  sql restore PATH             RESTORE SQL DATABASE (ROOT)",
    "  sql sync dataset NAME TABLE  COPY DATASET TO SQL (ROOT)",
    "  sql syncback TABLE NAME     COPY SQL TABLE TO DATASET (ROOT)",
    "  sql grant USER read|write    SET SQL PERMISSIONS (ROOT)",
    "  sql migrate VERSION          SET SQL SCHEMA VERSION (ROOT)",
    "  alias NAME COMMAND           CREATE COMMAND ALIAS",
    "  unalias NAME                 REMOVE COMMAND ALIAS",
    "  reboot                       RESTART NYXOS",
    "  recover fs                   RESTORE FS BACKUP (ROOT)",
    "  processes                    SHOW RUNNING SERVICES",
    "  loglevel LEVEL               SET ERROR LOG LEVEL",
    "  role USER ROLE              SET USER ROLE (ROOT)",
    "  monitor                     SHOW LIVE SYSTEM MONITOR",
    "  plugin list                 LIST TEXT PLUGINS",
    "  plugin add NAME TEXT        ADD A TEXT PLUGIN (ROOT)",
    "  plugin remove NAME          REMOVE A PLUGIN (ROOT)",
)
PASSWORD_ITERATIONS = 260000


def hash_password(password: str, salt: str = None) -> str:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        PASSWORD_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"


def is_password_hash(value: str) -> bool:
    return value.startswith("pbkdf2_sha256$")


def verify_password(password: str, stored: str) -> bool:
    if not is_password_hash(stored):
        return hmac.compare_digest(password, stored)
    try:
        algorithm, iterations, salt, expected = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, UnicodeEncodeError):
        return False


USERS = {
    "user": hash_password("user", "nyxos-default-user"),
}
ROOT_PASSWORD_HASH = hash_password("root", "nyxos-root-password")
FS_IMAGE_PATH = Path(__file__).with_name("fs.fs")
SQL_DB_PATH = Path(__file__).with_name("nyxos.db")
UPTIME_START = time.monotonic()
PROTECTED_DATASETS = {"system"}
MAX_LOGIN_ATTEMPTS = 3
SETTINGS = {
    "character_delay": 0.018,
    "line_delay": 0.25,
    "session_timeout": 0,
    "allow_remote_sql": False,
}
ERROR_LOG = []
AUDIT_LOG = []
DATASET_HISTORY = {}
ALIASES = {
    "ll": "history",
    "cls": "clearterm",
}
SQL_PERMISSIONS = {
    "user": "read",
}
USER_ROLES = {
    "user": "user",
}
PLUGINS = {}
SQL_HISTORY = []
SQL_SCHEMA_VERSION = 1
LOG_LEVEL = "INFO"
DEFAULT_BOOT_MESSAGES = list(BOOT_MESSAGES)
COLOR_ENABLED = True
COMMAND_MANUAL = {
    "help": "Show available commands.",
    "whoami": "Show the current user.",
    "en": "Enable root access with the root password.",
    "logout": "Return to the login screen.",
    "shutdown": "Confirm and stop the session. Root only.",
    "history": "Show commands entered this session.",
    "system info": "Show Python, host, and uptime information.",
    "dataset": "Manage persistent datasets.",
    "compile": "Compile supported two-number math expressions.",
    "ping": "Send one host-network ping.",
    "sql": "Start the local SQL server or run SQL client queries.",
}


def audit(event: str, username: str = "system") -> None:
    AUDIT_LOG.append(f"{datetime.now().isoformat(timespec='seconds')} {username}: {event}")
    if len(AUDIT_LOG) > 200:
        del AUDIT_LOG[:-200]
SQL_SERVER = None
SQL_SERVER_THREAD = None
SQL_SERVER_LOCK = threading.Lock()


class SQLRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        request_line = self.rfile.readline().decode("utf-8", errors="replace")
        try:
            request = json.loads(request_line)
            result = self.server.sql_service.execute(
                request["sql"],
                request.get("params", []),
                request.get("username", "user"),
                request.get("is_root", False),
            )
            response = {"ok": True, **result}
        except (
            KeyError,
            json.JSONDecodeError,
            sqlite3.Error,
            ValueError,
            PermissionError,
        ) as error:
            response = {"ok": False, "error": str(error)}
        self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))


class SQLTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, address, service):
        self.sql_service = service
        super().__init__(address, SQLRequestHandler)


class SQLService:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.connection = None
        self.explicit_transaction = False

    def start(self) -> int:
        global SQL_SERVER, SQL_SERVER_THREAD
        if SQL_SERVER is not None:
            return SQL_SERVER.server_address[1]
        self.connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        SQL_SERVER = SQLTCPServer(("127.0.0.1", 0), self)
        SQL_SERVER_THREAD = threading.Thread(
            target=SQL_SERVER.serve_forever,
            name="nyxos-sql-server",
            daemon=True,
        )
        SQL_SERVER_THREAD.start()
        return SQL_SERVER.server_address[1]

    def stop(self) -> None:
        global SQL_SERVER, SQL_SERVER_THREAD
        if SQL_SERVER is None:
            return
        SQL_SERVER.shutdown()
        SQL_SERVER.server_close()
        if self.connection is not None:
            self.connection.close()
        SQL_SERVER = None
        SQL_SERVER_THREAD = None
        self.connection = None

    def execute(self, statement: str, params=None, username="user", is_root=False):
        if not statement.strip():
            raise ValueError("EMPTY SQL STATEMENT")
        params = params or []
        first_word = statement.strip().split(None, 1)[0].upper()
        permission = SQL_PERMISSIONS.get(username, "read")
        if not is_root and permission != "write" and first_word not in {
            "SELECT", "PRAGMA", "WITH", "EXPLAIN"
        }:
            raise PermissionError("SQL WRITE ACCESS DENIED")
        with SQL_SERVER_LOCK:
            cursor = self.connection.execute(statement, params)
            if cursor.description:
                return {
                    "columns": [column[0] for column in cursor.description],
                    "rows": [list(row) for row in cursor.fetchall()],
                }
            if first_word == "BEGIN":
                self.explicit_transaction = True
            elif first_word in {"COMMIT", "ROLLBACK"}:
                self.explicit_transaction = False
            elif not self.explicit_transaction:
                self.connection.commit()
            return {"affected": cursor.rowcount}

    def dump(self, destination: Path) -> None:
        self.connection.commit()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.copy2(destination, Path(f"{destination}.bak"))
        temporary = Path(f"{destination}.tmp")
        backup = sqlite3.connect(temporary)
        try:
            self.connection.backup(backup)
            backup.commit()
        finally:
            backup.close()
        os.replace(temporary, destination)

    def restore(self, source: Path) -> None:
        if not source.exists():
            raise FileNotFoundError(source)
        self.connection.close()
        if self.database_path.exists():
            shutil.copy2(self.database_path, Path(f"{self.database_path}.bak"))
        shutil.copy2(source, self.database_path)
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row


SQL_SERVICE = SQLService(SQL_DB_PATH)


def load_filesystem() -> None:
    global LOG_LEVEL, SQL_SCHEMA_VERSION
    if not FS_IMAGE_PATH.exists():
        return
    try:
        image = json.loads(FS_IMAGE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    users = image.get("users")
    datasets = image.get("datasets")
    settings = image.get("settings")
    boot_messages = image.get("boot_messages")
    errors = image.get("errors")
    audit_log = image.get("audit_log")
    user_roles = image.get("user_roles")
    plugins = image.get("plugins")
    dataset_history = image.get("dataset_history")
    aliases = image.get("aliases")
    sql_permissions = image.get("sql_permissions")
    sql_history = image.get("sql_history")
    schema_version = image.get("sql_schema_version")
    log_level = image.get("log_level")
    migrated = False
    if isinstance(users, dict):
        USERS.clear()
        USERS.update(users)
        for username, password in list(USERS.items()):
            if isinstance(password, str) and not is_password_hash(password):
                USERS[username] = hash_password(password)
                migrated = True
    if isinstance(datasets, dict):
        DATASETS.clear()
        DATASETS.update(datasets)
    if isinstance(settings, dict):
        SETTINGS.update(settings)
    if isinstance(boot_messages, list) and all(
        isinstance(message, str) for message in boot_messages
    ):
        BOOT_MESSAGES[:] = boot_messages
    if isinstance(errors, list):
        ERROR_LOG[:] = [str(error) for error in errors]
    if isinstance(audit_log, list):
        AUDIT_LOG[:] = [str(entry) for entry in audit_log][-200:]
    if isinstance(user_roles, dict):
        USER_ROLES.update({str(key): str(value) for key, value in user_roles.items()})
    if isinstance(plugins, dict):
        PLUGINS.update({str(key): str(value) for key, value in plugins.items()})
    if isinstance(dataset_history, dict):
        DATASET_HISTORY.clear()
        DATASET_HISTORY.update(dataset_history)
    if isinstance(aliases, dict):
        ALIASES.update({str(key): str(value) for key, value in aliases.items()})
    if isinstance(sql_permissions, dict):
        SQL_PERMISSIONS.update(sql_permissions)
    if isinstance(sql_history, list):
        SQL_HISTORY[:] = [str(statement) for statement in sql_history][-100:]
    if isinstance(schema_version, int):
        SQL_SCHEMA_VERSION = schema_version
    if isinstance(log_level, str):
        LOG_LEVEL = log_level.upper()
    if migrated:
        save_filesystem()


def save_filesystem() -> None:
    image = {
        "users": USERS,
        "datasets": DATASETS,
        "settings": SETTINGS,
        "boot_messages": BOOT_MESSAGES,
        "errors": ERROR_LOG[-100:],
        "audit_log": AUDIT_LOG[-200:],
        "dataset_history": DATASET_HISTORY,
        "aliases": ALIASES,
        "sql_permissions": SQL_PERMISSIONS,
        "sql_history": SQL_HISTORY[-100:],
        "sql_schema_version": SQL_SCHEMA_VERSION,
        "log_level": LOG_LEVEL,
        "user_roles": USER_ROLES,
        "plugins": PLUGINS,
    }
    FS_IMAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    backup_path = Path(f"{FS_IMAGE_PATH}.bak")
    if FS_IMAGE_PATH.exists():
        for index in range(4, 0, -1):
            source = Path(f"{FS_IMAGE_PATH}.bak{index}")
            destination = Path(f"{FS_IMAGE_PATH}.bak{index + 1}")
            if source.exists():
                source.replace(destination)
        shutil.copy2(FS_IMAGE_PATH, backup_path)
        shutil.copy2(FS_IMAGE_PATH, Path(f"{FS_IMAGE_PATH}.bak1"))
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=FS_IMAGE_PATH.parent,
            prefix=f".{FS_IMAGE_PATH.name}.",
            delete=False,
        ) as temporary_file:
            json.dump(image, temporary_file, indent=2, sort_keys=True)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, FS_IMAGE_PATH)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
DATASETS = {
    "system": {
        "name": "NYXOS",
        "version": "2026",
        "status": "online",
    },
}
MATH_EXPRESSION = re.compile(r"^[\d\s+*/().-]+$")


def print_with_buffer(text: str, delay: float = 0.018) -> None:
    for character in text:
        sys.stdout.write(character)
        sys.stdout.flush()
        time.sleep(delay)


def configure_readline() -> None:
    commands = sorted({line.strip().split()[0] for line in HELP_LINES})

    def complete(text, state):
        matches = [command for command in commands if command.startswith(text)]
        return matches[state] if state < len(matches) else None

    readline.set_completer(complete)
    readline.parse_and_bind("tab: complete")


def print_line(text: str, delay: float = 0.018) -> None:
    if COLOR_ENABLED:
        text = f"\033[96m{text}\033[0m"
    print_with_buffer(text, delay)
    sys.stdout.write("\n")
    sys.stdout.flush()


def clear_terminal() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def run_boot_sequence(character_delay=None, line_delay=None) -> None:
    if character_delay is None:
        character_delay = float(SETTINGS["character_delay"])
    if line_delay is None:
        line_delay = float(SETTINGS["line_delay"])
    print_line(BANNER, character_delay)
    for message in BOOT_MESSAGES:
        time.sleep(line_delay)
        print_line(message, character_delay)


def login(input_func=input, password_func=getpass.getpass) -> str:
    for _ in range(MAX_LOGIN_ATTEMPTS):
        username = input_func("ENTER USERID ===> ")
        password = password_func("ENTER PASSWORD => ")
        stored_password = USERS.get(username)
        if stored_password is not None and verify_password(password, stored_password):
            if not is_password_hash(stored_password):
                USERS[username] = hash_password(password)
                save_filesystem()
            audit("login success", username)
            return username
        print_line("INVALID LOGON")
        audit("login failure", username)
    print_line("LOGIN LOCKED: TOO MANY ATTEMPTS")
    return None


def show_dataset(name: str, is_root: bool = False) -> None:
    if name in PROTECTED_DATASETS and not is_root:
        print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        return
    dataset = DATASETS.get(name)
    if dataset is None:
        print_line("DATASET NOT FOUND")
        return
    print_line(f"DATASET: {name}")
    for key, value in dataset.items():
        print_line(f"{key} = {value}")


def snapshot_dataset(name: str) -> None:
    if name in DATASETS:
        DATASET_HISTORY.setdefault(name, []).append(copy.deepcopy(DATASETS[name]))
        DATASET_HISTORY[name] = DATASET_HISTORY[name][-10:]


def edit_dataset(name: str, input_func=input, is_root: bool = False) -> None:
    if name in PROTECTED_DATASETS and not is_root:
        print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        return
    dataset = DATASETS.setdefault(name, {})
    snapshot_dataset(name)
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
    if MATH_EXPRESSION.fullmatch(expression) is None:
        return None

    try:
        tree = ast.parse(expression, mode="eval").body

        def evaluate(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return Decimal(str(node.value))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
                value = evaluate(node.operand)
                return -value if isinstance(node.op, ast.USub) else value
            if isinstance(node, ast.BinOp):
                left = evaluate(node.left)
                right = evaluate(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    if right == 0:
                        return "DIVISION BY ZERO"
                    return left / right
            raise ValueError

        return evaluate(tree)
    except (ValueError, InvalidOperation, SyntaxError, TypeError, ZeroDivisionError):
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


def handle_dataset(
    command_parts: List[str], input_func=input, is_root: bool = False
) -> None:
    action = command_parts[1].lower() if len(command_parts) > 1 else "list"
    if action == "list":
        for name in DATASETS:
            print_line(name)
    elif action == "view" and len(command_parts) > 2:
        show_dataset(command_parts[2], is_root)
    elif action == "edit" and len(command_parts) > 2:
        edit_dataset(command_parts[2], input_func, is_root)
    elif action == "delete" and len(command_parts) > 2:
        name = command_parts[2]
        if name in PROTECTED_DATASETS and not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        elif name not in DATASETS:
            print_line("DATASET NOT FOUND")
        else:
            snapshot_dataset(name)
            del DATASETS[name]
            audit(f"dataset delete {name}")
            save_filesystem()
            print_line(f"DATASET DELETED: {name}")
    elif action == "rename" and len(command_parts) > 3:
        old_name, new_name = command_parts[2:4]
        if old_name in PROTECTED_DATASETS and not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        elif old_name not in DATASETS:
            print_line("DATASET NOT FOUND")
        elif new_name in DATASETS:
            print_line("DATASET ALREADY EXISTS")
        else:
            snapshot_dataset(old_name)
            DATASETS[new_name] = DATASETS.pop(old_name)
            audit(f"dataset rename {old_name} {new_name}")
            save_filesystem()
            print_line(f"DATASET RENAMED: {old_name} -> {new_name}")
    elif action == "search" and len(command_parts) > 2:
        search_text = " ".join(command_parts[2:]).lower()
        for name, dataset in DATASETS.items():
            if name in PROTECTED_DATASETS and not is_root:
                continue
            if search_text in name.lower() or any(
                search_text in str(key).lower()
                or search_text in str(value).lower()
                for key, value in dataset.items()
            ):
                print_line(name)
    elif action == "export" and len(command_parts) > 3:
        name, path = command_parts[2:4]
        if name in PROTECTED_DATASETS and not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        elif name not in DATASETS:
            print_line("DATASET NOT FOUND")
        else:
            try:
                Path(path).write_text(
                    json.dumps({name: DATASETS[name]}, indent=2) + "\n",
                    encoding="utf-8",
                )
                print_line(f"DATASET EXPORTED: {path}")
            except OSError:
                print_line("DATASET EXPORT FAILED")
    elif action == "import" and len(command_parts) > 3:
        name, path = command_parts[2:4]
        if name in PROTECTED_DATASETS and not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        else:
            try:
                imported = json.loads(Path(path).read_text(encoding="utf-8"))
                dataset = imported.get(name)
                if dataset is None and len(imported) == 1:
                    dataset = next(iter(imported.values()))
                if not isinstance(dataset, dict):
                    raise ValueError
                snapshot_dataset(name)
                DATASETS[name] = dataset
                audit(f"dataset import {name}")
                save_filesystem()
                print_line(f"DATASET IMPORTED: {name}")
            except (OSError, ValueError, json.JSONDecodeError):
                print_line("DATASET IMPORT FAILED")
    elif action == "rollback" and len(command_parts) > 2:
        name = command_parts[2]
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        elif not DATASET_HISTORY.get(name):
            print_line("NO DATASET BACKUP")
        else:
            DATASETS[name] = DATASET_HISTORY[name].pop()
            save_filesystem()
            print_line(f"DATASET ROLLED BACK: {name}")
    else:
        print_line(
            "USAGE: dataset list | view NAME | edit NAME | "
            "delete NAME | rename OLD NEW | search TEXT | "
            "export NAME PATH | import NAME PATH | rollback NAME"
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


def format_sql_result(result) -> None:
    if "columns" in result:
        print_line(" | ".join(result["columns"]))
        for row in result["rows"]:
            print_line(" | ".join("NULL" if value is None else str(value) for value in row))
        print_line(f"{len(result['rows'])} ROW(S)")
    else:
        print_line(f"AFFECTED: {result.get('affected', 0)}")


def run_sql_client(
    statement: str, username: str = "user", is_root: bool = False, params=None
) -> None:
    if SQL_SERVER is None:
        print_line("SQL SERVER IS NOT RUNNING")
        return
    SQL_HISTORY.append(statement)
    audit(f"sql query: {statement[:120]}", username)
    save_filesystem()
    try:
        with socket.create_connection(
            ("127.0.0.1", SQL_SERVER.server_address[1]), timeout=5
        ) as connection:
            connection.sendall(
                (
                    json.dumps(
                        {
                            "sql": statement,
                            "params": params or [],
                            "username": username,
                            "is_root": is_root,
                        }
                    )
                    + "\n"
                ).encode("utf-8")
            )
            response = connection.makefile("r", encoding="utf-8").readline()
        result = json.loads(response)
    except (OSError, json.JSONDecodeError) as error:
        print_line(f"SQL CLIENT ERROR: {error}")
        return
    if not result.get("ok"):
        print_line(f"SQL ERROR: {result.get('error', 'UNKNOWN ERROR')}")
        return
    format_sql_result(result)


def handle_sql(
    command_parts: List[str],
    is_root: bool,
    username: str = "user",
    input_func=input,
) -> None:
    global SQL_SCHEMA_VERSION
    action = command_parts[1].lower() if len(command_parts) > 1 else "status"
    if action == "start":
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        else:
            port = SQL_SERVICE.start()
            print_line(f"SQL SERVER STARTED: 127.0.0.1:{port}")
    elif action == "reconnect":
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        else:
            SQL_SERVICE.stop()
            port = SQL_SERVICE.start()
            print_line(f"SQL SERVER RECONNECTED: 127.0.0.1:{port}")
    elif action == "stop":
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        else:
            SQL_SERVICE.stop()
            print_line("SQL SERVER STOPPED")
    elif action == "status":
        if SQL_SERVER is None:
            print_line("SQL SERVER: STOPPED")
        else:
            print_line(f"SQL SERVER: RUNNING ON PORT {SQL_SERVER.server_address[1]}")
    elif action == "backup" and len(command_parts) > 2 and command_parts[2].lower() == "list":
        for path in sorted(SQL_DB_PATH.parent.glob(f"{SQL_DB_PATH.name}*")):
            if path.is_file():
                print_line(f"{path.name} {path.stat().st_size} bytes")
    elif action == "tables":
        run_sql_client(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name",
            username,
            is_root,
        )
    elif action == "history":
        if not SQL_HISTORY:
            print_line("NO SQL HISTORY")
        for index, statement in enumerate(SQL_HISTORY, 1):
            print_line(f"{index}: {statement}")
    elif action in ("query", "client") and len(command_parts) > 2:
        query_parts = command_parts[2:]
        params = []
        if "--param" in query_parts:
            separator = query_parts.index("--param")
            params = query_parts[separator + 1:]
            query_parts = query_parts[:separator]
        run_sql_client(" ".join(query_parts), username, is_root, params)
    elif action == "prompt":
        if SQL_SERVER is None:
            print_line("SQL SERVER IS NOT RUNNING")
        else:
            print_line("SQL PROMPT: type EXIT to leave")
            while True:
                statement = input_func("SQL> ").strip()
                if statement.lower() in ("exit", "quit"):
                    break
                if statement:
                    run_sql_client(statement, username, is_root)
    elif action == "schema" and len(command_parts) > 2:
        table_name = command_parts[2].replace('"', '""')
        run_sql_client(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            f"AND name = \"{table_name}\"",
            username,
            is_root,
        )
    elif action in ("dump", "restore") and len(command_parts) > 2:
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        elif SQL_SERVER is None:
            print_line("SQL SERVER IS NOT RUNNING")
        else:
            path = Path(command_parts[2])
            try:
                if action == "dump":
                    SQL_SERVICE.dump(path)
                    print_line(f"SQL DUMP CREATED: {path}")
                else:
                    SQL_SERVICE.restore(path)
                    print_line(f"SQL DATABASE RESTORED: {path}")
            except (OSError, sqlite3.Error):
                print_line(f"SQL {action.upper()} FAILED")
    elif action == "sync" and len(command_parts) > 4 and command_parts[2].lower() == "dataset":
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        else:
            dataset_name, table_name = command_parts[3:5]
            dataset = DATASETS.get(dataset_name)
            if dataset is None:
                print_line("DATASET NOT FOUND")
            else:
                quoted_table = table_name.replace('"', '""')
                run_sql_client(
                    f'CREATE TABLE IF NOT EXISTS "{quoted_table}" '
                    "(key TEXT PRIMARY KEY, value TEXT)", username, True
                )
                run_sql_client(f'DELETE FROM "{quoted_table}"', username, True)
                for key, value in dataset.items():
                    run_sql_client(
                        f'INSERT INTO "{quoted_table}" (key, value) VALUES (?, ?)',
                        username,
                        True,
                        [str(key), str(value)],
                    )
                print_line(f"DATASET SYNCED: {dataset_name} -> {table_name}")
    elif action == "syncback" and len(command_parts) > 3:
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        else:
            table_name, dataset_name = command_parts[2:4]
            quoted_table = table_name.replace('"', '""')
            try:
                result = SQL_SERVICE.execute(
                    f'SELECT key, value FROM "{quoted_table}"',
                    username=username,
                    is_root=True,
                )
                DATASETS[dataset_name] = {str(row[0]): row[1] for row in result["rows"]}
                save_filesystem()
                print_line(f"SQL SYNCED BACK: {table_name} -> {dataset_name}")
            except sqlite3.Error:
                print_line("SQL SYNC BACK FAILED")
    elif action == "grant" and len(command_parts) > 3:
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        elif command_parts[2] not in USERS:
            print_line("USER NOT FOUND")
        elif command_parts[3].lower() not in ("read", "write"):
            print_line("USAGE: sql grant USER read|write")
        else:
            SQL_PERMISSIONS[command_parts[2]] = command_parts[3].lower()
            save_filesystem()
            print_line("SQL PERMISSION UPDATED")
    elif action == "migrate" and len(command_parts) > 2:
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        else:
            try:
                version = int(command_parts[2])
                if version < SQL_SCHEMA_VERSION:
                    print_line("SQL SCHEMA CANNOT MOVE BACKWARD")
                else:
                    SQL_SCHEMA_VERSION = version
                    save_filesystem()
                    print_line(f"SQL SCHEMA VERSION: {version}")
            except ValueError:
                print_line("USAGE: sql migrate VERSION")
    else:
        print_line(
            'USAGE: sql start|stop|status|tables|schema TABLE|query "SQL"|'
            'prompt|dump PATH|restore PATH|sync dataset NAME TABLE'
        )


def show_errors() -> None:
    if not ERROR_LOG:
        print_line("NO ERRORS")
        return
    for error in ERROR_LOG:
        print_line(error)


def handle_boot_messages(command_parts: List[str], is_root: bool) -> None:
    action = command_parts[1].lower() if len(command_parts) > 1 else "list"
    if action == "list":
        for index, message in enumerate(BOOT_MESSAGES, 1):
            print_line(f"{index}: {message}")
    elif action == "add" and len(command_parts) > 2:
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        else:
            BOOT_MESSAGES.append(" ".join(command_parts[2:]))
            save_filesystem()
            print_line("BOOT MESSAGE ADDED")
    elif action == "clear":
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        else:
            BOOT_MESSAGES[:] = DEFAULT_BOOT_MESSAGES
            save_filesystem()
            print_line("BOOT MESSAGES RESET")
    else:
        print_line("USAGE: bootmsg list | add TEXT | clear")


def handle_settings(command_parts: List[str], is_root: bool) -> None:
    if len(command_parts) == 1:
        for key, value in SETTINGS.items():
            print_line(f"{key} = {value}")
        return
    if len(command_parts) != 4 or command_parts[1].lower() != "set":
        print_line("USAGE: settings | settings set KEY VALUE")
        return
    if not is_root:
        print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        return
    key, raw_value = command_parts[2], command_parts[3]
    if key not in SETTINGS:
        print_line("UNKNOWN SETTING")
        return
    try:
        value = float(raw_value)
        if value < 0:
            raise ValueError
    except ValueError:
        print_line("SETTING MUST BE A NON-NEGATIVE NUMBER")
        return
    SETTINGS[key] = value
    save_filesystem()
    print_line(f"SETTING UPDATED: {key}")


def show_system_info() -> None:
    print_line(f"NYXOS: {BANNER}")
    print_line(f"PYTHON: {sys.version.split()[0]}")
    print_line(f"HOST: {socket.gethostname()}")
    show_uptime()


def add_user(input_func=input, password_func=getpass.getpass) -> None:
    username = input_func("NEW USERNAME => ").strip()
    if not username or any(character.isspace() for character in username):
        print_line("INVALID USERNAME")
        return
    if username in USERS:
        print_line("USER ALREADY EXISTS")
        return
    password = password_func("NEW PASSWORD => ")
    if not password:
        print_line("PASSWORD REQUIRED")
        return
    USERS[username] = hash_password(password)
    USER_ROLES[username] = "user"
    SQL_PERMISSIONS[username] = "read"
    save_filesystem()
    print_line(f"USER ADDED: {username}")


def delete_user(command_parts: List[str], username: str) -> None:
    if len(command_parts) < 2:
        print_line("USAGE: deluser NAME")
        return
    target = command_parts[1]
    if target == username or target == "user":
        print_line("CANNOT DELETE ACTIVE OR DEFAULT USER")
    elif target not in USERS:
        print_line("USER NOT FOUND")
    else:
        del USERS[target]
        USER_ROLES.pop(target, None)
        SQL_PERMISSIONS.pop(target, None)
        save_filesystem()
        print_line(f"USER DELETED: {target}")


def show_manual(command_parts: List[str]) -> None:
    topic = " ".join(command_parts[1:]).lower()
    description = COMMAND_MANUAL.get(topic)
    if description is None:
        print_line("NO MANUAL ENTRY")
    else:
        print_line(f"{topic}: {description}")


def show_audit(is_root: bool) -> None:
    if not is_root:
        print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        return
    if not AUDIT_LOG:
        print_line("NO AUDIT EVENTS")
    for entry in AUDIT_LOG:
        print_line(entry)


def set_role(command_parts: List[str], is_root: bool) -> None:
    if not is_root:
        print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        return
    if len(command_parts) != 3 or command_parts[1] not in USERS:
        print_line("USAGE: role USER guest|user|operator|root")
        return
    role = command_parts[2].lower()
    if role not in ("guest", "user", "operator", "root"):
        print_line("USAGE: role USER guest|user|operator|root")
        return
    USER_ROLES[command_parts[1]] = role
    SQL_PERMISSIONS[command_parts[1]] = "write" if role in ("operator", "root") else "read"
    save_filesystem()
    audit(f"role changed to {role}", command_parts[1])
    print_line(f"ROLE UPDATED: {command_parts[1]} -> {role}")


def show_monitor() -> None:
    print_line("NYXOS SYSTEM MONITOR")
    show_processes()
    print_line(f"USERS: {len(USERS)}")
    print_line(f"DATASETS: {len(DATASETS)}")
    print_line(f"SQL HISTORY: {len(SQL_HISTORY)}")
    show_uptime()


def handle_plugin(command_parts: List[str], is_root: bool) -> None:
    action = command_parts[1].lower() if len(command_parts) > 1 else "list"
    if action == "list":
        for name in PLUGINS:
            print_line(name)
    elif action == "add" and len(command_parts) > 3:
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        else:
            PLUGINS[command_parts[2]] = " ".join(command_parts[3:])
            save_filesystem()
            print_line(f"PLUGIN ADDED: {command_parts[2]}")
    elif action == "remove" and len(command_parts) > 2:
        if not is_root:
            print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        else:
            PLUGINS.pop(command_parts[2], None)
            save_filesystem()
            print_line(f"PLUGIN REMOVED: {command_parts[2]}")
    else:
        print_line("USAGE: plugin list | add NAME TEXT | remove NAME")


def show_processes() -> None:
    print_line("nyxos-main: RUNNING")
    print_line(
        "nyxos-sql-server: "
        + ("RUNNING" if SQL_SERVER is not None else "STOPPED")
    )


def recover_filesystem(is_root: bool) -> None:
    if not is_root:
        print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        return
    backup_path = Path(f"{FS_IMAGE_PATH}.bak")
    if not backup_path.exists():
        print_line("FS BACKUP NOT FOUND")
        return
    try:
        shutil.copy2(backup_path, FS_IMAGE_PATH)
        load_filesystem()
        print_line("FS BACKUP RESTORED")
    except OSError:
        print_line("FS RECOVERY FAILED")


def show_help(topic: str = "") -> None:
    if topic:
        groups = {
            "sql": ("sql",),
            "dataset": ("dataset", "compile dataset"),
            "user": ("user", "whoami", "en", "adduser", "deluser", "role"),
        }
        prefixes = groups.get(topic.lower())
        if prefixes is None:
            print_line("HELP TOPICS: sql, dataset, user")
            return
        for line in HELP_LINES:
            if any(prefix in line for prefix in prefixes):
                print_line(line)
        return
    for line in HELP_LINES:
        print_line(line)


def command_loop(
    input_func=input,
    password_func=getpass.getpass,
    username="user",
    clear_func=clear_terminal,
) -> None:
    is_root = False
    history = []
    last_activity = time.monotonic()
    while True:
        prompt = "# " if is_root else "> "
        timeout = float(SETTINGS.get("session_timeout", 0))
        if timeout > 0 and input_func is input and sys.stdin.isatty():
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
            if not ready and time.monotonic() - last_activity >= timeout:
                print_line("SESSION TIMED OUT")
                return "logout"
        command = input_func(prompt).strip()
        last_activity = time.monotonic()
        command_parts = shlex.split(command)
        if not command_parts:
            continue
        history.append(command)
        if command_parts[0].lower() in ALIASES:
            command_parts = shlex.split(
                ALIASES[command_parts[0].lower()]
                + " "
                + " ".join(command_parts[1:])
            )

        command_name = command_parts[0].lower()
        if command_name == "help":
            show_help(command_parts[1] if len(command_parts) > 1 else "")
        elif command_name == "clearterm":
            clear_func()
        elif command_name == "clear":
            clear_func()
        elif command_name == "date":
            print_line(datetime.now().strftime("%Y-%m-%d"))
        elif command_name == "time":
            print_line(datetime.now().strftime("%H:%M:%S"))
        elif command_name == "uptime":
            show_uptime()
        elif command_name == "history":
            for index, previous_command in enumerate(history, 1):
                print_line(f"{index}: {previous_command}")
        elif command_name == "man":
            show_manual(command_parts)
        elif command_name == "sql":
            handle_sql(command_parts, is_root, username, input_func)
        elif command_name == "system" and len(command_parts) > 1:
            if command_parts[1].lower() == "info":
                show_system_info()
            elif command_parts[1].lower() == "processes":
                show_processes()
            else:
                print_line("USAGE: system info")
        elif command_name == "status":
            show_system_info()
        elif command_name == "processes":
            show_processes()
        elif command_name == "errors":
            show_errors()
        elif command_name == "audit":
            show_audit(is_root)
        elif command_name == "role":
            set_role(command_parts, is_root)
        elif command_name == "monitor":
            show_monitor()
        elif command_name == "plugin":
            handle_plugin(command_parts, is_root)
        elif command_name == "color" and len(command_parts) > 1:
            global COLOR_ENABLED
            COLOR_ENABLED = command_parts[1].lower() == "on"
            print_line(f"COLORS {'ENABLED' if COLOR_ENABLED else 'DISABLED'}")
        elif command_name == "loglevel" and len(command_parts) > 1:
            level = command_parts[1].upper()
            if level not in ("DEBUG", "INFO", "WARN", "ERROR", "OFF"):
                print_line("USAGE: loglevel DEBUG|INFO|WARN|ERROR|OFF")
            else:
                global LOG_LEVEL
                LOG_LEVEL = level
                save_filesystem()
                print_line(f"LOG LEVEL: {LOG_LEVEL}")
        elif command_name == "alias" and len(command_parts) > 2:
            ALIASES[command_parts[1].lower()] = " ".join(command_parts[2:])
            save_filesystem()
            print_line(f"ALIAS CREATED: {command_parts[1]}")
        elif command_name == "unalias" and len(command_parts) > 1:
            ALIASES.pop(command_parts[1].lower(), None)
            save_filesystem()
            print_line(f"ALIAS REMOVED: {command_parts[1]}")
        elif command_name == "recover" and len(command_parts) > 1 and command_parts[1].lower() == "fs":
            recover_filesystem(is_root)
        elif command_name == "bootmsg":
            handle_boot_messages(command_parts, is_root)
        elif command_name == "settings":
            handle_settings(command_parts, is_root)
        elif command_name in ("hostname", "resolve", "ping"):
            handle_network(command_parts)
        elif command_name == "whoami":
            print_line("root" if is_root else username)
        elif command_name == "en":
            if is_root:
                print_line("ALREADY ROOT")
            elif verify_password(
                password_func("ROOT PASSWORD => "), ROOT_PASSWORD_HASH
            ):
                is_root = True
                print_line("ROOT ACCESS ENABLED")
            else:
                print_line("ROOT ACCESS DENIED")
        elif command_name == "shutdown":
            if is_root:
                confirmation = input_func("CONFIRM SHUTDOWN [y/N]: ").strip().lower()
                if confirmation in ("y", "yes"):
                    save_filesystem()
                    SQL_SERVICE.stop()
                    print_line("SYSTEM SHUTDOWN")
                    return "shutdown"
                print_line("SHUTDOWN CANCELLED")
            else:
                print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        elif command_name == "dataset":
            handle_dataset(command_parts, input_func, is_root)
        elif command_name == "adduser":
            if is_root:
                add_user(input_func, password_func)
            else:
                print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        elif command_name == "deluser":
            if is_root:
                delete_user(command_parts, username)
            else:
                print_line("PERMISSION DENIED: ROOT ACCESS REQUIRED")
        elif command_name == "logout":
            print_line("LOGGING OUT")
            return "logout"
        elif command_name == "reboot":
            print_line("REBOOTING NYXOS")
            return "reboot"
        elif (
            command_name == "compile"
            and len(command_parts) == 3
            and command_parts[1].lower() == "dataset"
        ):
            compile_dataset(command_parts[2])
        else:
            if LOG_LEVEL != "OFF":
                ERROR_LOG.append(f"UNKNOWN COMMAND: {command}")
            print_line("UNKNOWN COMMAND")


def main() -> None:
    configure_readline()
    load_filesystem()
    try:
        while True:
            run_boot_sequence()
            time.sleep(0.5)
            print_line(LOGIN_SCREEN)
            username = login()
            if username is None:
                break
            result = command_loop(username=username)
            if result == "shutdown":
                break
    finally:
        SQL_SERVICE.stop()


if __name__ == "__main__":
    main()
