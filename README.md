# NYXOS 2026

A small Python-based terminal simulation with a retro boot sequence, TSO-style login, persistent datasets, and a command prompt.

## Files

- `System.py` - Main program.
- `fs.fs` - Persistent JSON storage containing datasets only.
- `nyxos.db` - Persistent local SQL database created by the SQL server.
- `README.md` - Project documentation.

## Run

From the project directory:

```sh
python3 System.py
```

The program will:

1. Print the `NYXOS 2026` boot banner.
2. Run the boot status checks.
3. Show the TSO-style login screen.
4. Open the user command prompt.

The boot and status text use a character-by-character output buffer to create a small typing delay.

## Login

The default user account is:

```text
User ID: user
Password: user
```

After login, the normal prompt is `>`. Invalid credentials are rejected and the login is shown again.

## Commands

| Command | Description |
| --- | --- |
| `help` | Show the available commands. |
| `whoami` | Show the current username. |
| `en` | Enable root access after entering the root password. |
| `shutdown` | Shut down the session. Requires root access. |
| `clearterm` | Clear the terminal using the host operating system command. |
| `clear` | Alias for `clearterm`. |
| `date` | Show the host's local date. |
| `time` | Show the host's local time. |
| `uptime` | Show how long the NYXOS process has been running. |
| `status` | Show system information and uptime. |
| `system info` | Show Python, host, and uptime information. |
| `hostname` | Show the host computer's hostname. |
| `resolve HOST` | Resolve a hostname through the host network. |
| `ping HOST` | Send one host-network ping and report its result. |
| `history` | Show commands entered during this session. |
| `man COMMAND` | Show built-in command documentation. |
| `logout` | Return to the login screen. |
| `color on/off` | Toggle retro terminal colors. |
| `errors` | Show the session error log. |
| `audit` | Show the security audit log as root. |
| `settings` | Show startup settings. |
| `settings set KEY VALUE` | Change startup timing settings as root. |
| `bootmsg list` | List boot messages. |
| `bootmsg add TEXT` | Add a boot message as root. |
| `bootmsg clear` | Reset boot messages as root. |
| `adduser` | Add a persistent user as root. |
| `deluser NAME` | Delete a user as root. |
| `dataset list` | List all datasets. |
| `dataset view NAME` | Display a dataset's values. |
| `dataset edit NAME` | Create or edit a dataset. |
| `dataset delete NAME` | Delete and persist a dataset. |
| `dataset rename OLD NEW` | Rename and persist a dataset. |
| `dataset search TEXT` | Search dataset names, keys, and values. |
| `dataset export NAME PATH` | Export a dataset to a host JSON file. |
| `dataset import NAME PATH` | Import a JSON dataset under a chosen name. |
| `dataset rollback NAME` | Restore the previous dataset version as root. |
| `compile dataset NAME` | Evaluate supported math expressions in a dataset. |
| `reboot` | Restart the NYXOS login session. |
| `alias NAME COMMAND` | Create a persistent command alias. |
| `unalias NAME` | Remove a command alias. |
| `recover fs` | Restore `fs.fs` from its backup as root. |
| `processes` | Show NYXOS and SQL service status. |
| `loglevel LEVEL` | Set the error log level. |
| `role USER ROLE` | Assign `guest`, `user`, `operator`, or `root` privileges. |
| `audit` | Show security-sensitive events as root. |
| `monitor` | Show live service and storage counts. |
| `plugin list` | List persistent text plugins. |
| `plugin add NAME TEXT` | Add a root-managed text plugin. |
| `plugin remove NAME` | Remove a plugin as root. |
| `role USER ROLE` | Set a user role: `guest`, `user`, `operator`, or `root`. |
| `monitor` | Show live service, user, dataset, and SQL counts. |
| `sql start` | Start the localhost SQL server. Root only. |
| `sql stop` | Stop the localhost SQL server. Root only. |
| `sql reconnect` | Restart the local SQL server connection. Root only. |
| `sql status` | Show SQL server status. |
| `sql tables` | List SQL tables through the client. |
| `sql schema TABLE` | Show a table schema through the client. |
| `sql query "SQL"` | Send SQL to the local server. |
| `sql prompt` | Open an interactive SQL client prompt. |
| `sql dump PATH` | Create a SQL database backup as root. |
| `sql restore PATH` | Restore a SQL database backup as root. |
| `sql sync dataset NAME TABLE` | Copy a dataset into an SQL table as root. |
| `sql grant USER read\|write` | Set SQL permissions as root. |
| `sql migrate VERSION` | Set the SQL schema version as root. |
| `sql history` | Show persistent SQL query history. |
| `sql backup list` | List local SQL database backups. |
| `sql syncback TABLE NAME` | Copy a key/value SQL table into a dataset as root. |

## Root Access

Run:

```text
en
```

Then enter:

```text
root
```

A successful elevation changes the prompt to `#`. `whoami` reports `root`, and `shutdown` becomes available.

The default account is stored in `fs.fs`. Passwords are stored as PBKDF2-SHA256 hashes. Existing plaintext accounts from older versions are upgraded automatically after loading or successful login. New accounts can be created with `adduser` after root elevation. This is still a demo login system and is not intended for production security.

After three failed login attempts, the login is locked for that process and the program exits.

## Dataset Editor

Start an editor with:

```text
dataset edit math
```

Enter either a key-value pair:

```text
name=value
```

or a bare two-number math expression:

```text
5 + 5
5 - 4
5 * 3
8 / 2
```

Bare expressions are stored under numbered keys. Type `SAVE` to persist the dataset.

Example:

```text
DATASET EDIT> 5 + 5
ADDED 1: 5 + 5
DATASET EDIT> 5 - 4
ADDED 2: 5 - 4
DATASET EDIT> SAVE
DATASET SAVED
```

## Dataset Compiler

Compile a dataset with:

```text
compile dataset math
```

Expressions containing numbers, parentheses, and these operators are evaluated:

```text
number + number
number - number
number * number
number / number
(number + number) * number
```

Each expression is output separately. Division by zero is reported as `DIVISION BY ZERO`. Other non-math values are skipped.

Example output:

```text
1: 5 + 5 = 10
2: 5 - 4 = 1
```

## Persistence

`fs.fs` is a JSON file managed by `System.py`. Its current structure is:

```json
{
  "users": {
    "user": "pbkdf2_sha256$..."
  },
  "datasets": {
    "system": {
      "name": "NYXOS",
      "status": "online",
      "version": "2026"
    }
  },
  "settings": {
    "character_delay": 0.018,
    "line_delay": 0.25,
    "session_timeout": 0
  },
  "boot_messages": ["..."],
  "errors": [],
  "dataset_history": {},
  "aliases": {
    "ll": "history"
  },
  "sql_permissions": {
    "user": "read"
  },
  "sql_history": [],
  "log_level": "INFO"
}
```

Datasets, users, settings, boot messages, and errors are loaded when the program starts and saved atomically when:

- A dataset editor receives `SAVE`.
- A dataset is renamed, deleted, imported, or a user is changed.
- A root startup setting or boot message is changed.
- The session shuts down successfully.

There is no virtual file system. All persistent application data is stored under `datasets` in `fs.fs`.

The storage write uses a temporary file followed by an atomic replacement, reducing the chance of a partially written `fs.fs` if the process stops during a save. Before replacement, the previous image is copied to `fs.fs.bak`. The `system` dataset is protected from normal users.

## Host Network Commands

Network commands use the host operating system and network stack. `resolve` uses Python DNS resolution, while `ping` invokes the host `ping` executable without a shell. Targets are passed as arguments, so shell syntax is not interpreted.

## SQL Server and Client

Start the local SQL server as root:

```text
sql start
```

The server binds to `127.0.0.1` only and chooses an available local port. The shell client connects to that server with commands such as:

```text
sql query "CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT)"
sql query "INSERT INTO people (name) VALUES ('Nyx')"
sql query "SELECT * FROM people"
sql query "UPDATE people SET name='NYXOS' WHERE id=1"
sql query "DELETE FROM people WHERE id=1"
sql tables
sql schema people
sql query "INSERT INTO people (name) VALUES (?)" --param Nyx
sql query "BEGIN"
sql query "COMMIT"
sql dump people.db.backup
```

The database uses Python's built-in SQLite library and persists to `nyxos.db`. The service accepts normal SQLite SQL, including `CREATE TABLE`, `INSERT`, `SELECT`, `UPDATE`, `DELETE`, `DROP TABLE`, `BEGIN`, `COMMIT`, and `ROLLBACK`. Prepared values can be supplied with `--param`; these are passed to SQLite separately from the SQL string. SQL write permissions default to read-only for normal users and can be changed with `sql grant`. SQL schema versions are tracked in `fs.fs` and can be advanced with `sql migrate VERSION`. It is intentionally local-only and is not exposed to the network.
