# NYXOS 2026

A small Python-based terminal simulation with a retro boot sequence, TSO-style login, persistent datasets, and a command prompt.

## Files

- `System.py` - Main program.
- `fs.fs` - Persistent JSON storage containing datasets only.
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
| `dataset list` | List all datasets. |
| `dataset view NAME` | Display a dataset's values. |
| `dataset edit NAME` | Create or edit a dataset. |
| `compile dataset NAME` | Evaluate supported math expressions in a dataset. |

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

This is a demo login system. The credentials are stored directly in `System.py` and are not intended for real security.

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

Only expressions matching this form are evaluated:

```text
number + number
number - number
number * number
number / number
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
  "datasets": {
    "system": {
      "name": "NYXOS",
      "status": "online",
      "version": "2026"
    }
  }
}
```

Datasets are loaded when the program starts and saved when:

- A dataset editor receives `SAVE`.
- The session shuts down successfully.

There is no virtual file system. All persistent application data is stored under `datasets` in `fs.fs`.
