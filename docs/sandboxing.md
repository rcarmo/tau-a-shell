# macOS sandboxing

Tau Prime sandboxes the `tau` command by default on macOS. The CLI re-executes itself through `/usr/bin/sandbox-exec`, which applies one Seatbelt profile to Tau and every process it launches.

The implementation is deliberately filesystem-focused: reads, network access and process execution continue to work, while writes are limited to the project and the small set of directories Tau needs for its own state.

## Startup flow

The sandbox is established before Tau constructs a provider, opens a session or starts the TUI:

1. The CLI parses enough of the command line to determine `--cwd` and `--no-sandbox`.
2. On macOS, `should_enter_macos_sandbox()` checks that sandboxing is enabled and that this is not already the re-executed process.
3. `enter_macos_sandbox()` validates `/usr/bin/sandbox-exec`, resolves the `tau` executable and checks the selected working directory.
4. Tau prepares its configuration, log and temporary directories.
5. Tau generates an inline Seatbelt profile and replaces itself with `sandbox-exec` through `os.execve()`.
6. The replacement process receives the original arguments and `TAU_MACOS_SANDBOXED=1`, which prevents another re-exec.

The resulting command is equivalent to:

```sh
/usr/bin/sandbox-exec -p "$PROFILE" /path/to/tau [original arguments]
```

There is no wrapper process left behind. The sandboxed invocation replaces the original Tau process.

## Filesystem policy

The generated profile starts with normal macOS permissions, denies filesystem writes globally, then adds narrow write exceptions:

```scheme
(version 1)
(allow default)
(deny file-write*)
(allow file-write* (subpath "/selected/project"))
(allow file-write* (subpath "/resolved/tau/config"))
(allow file-write* (subpath "/resolved/tau/logs"))
(allow file-write* (subpath "/resolved/tmpdir"))
(allow file-write* (literal "/dev/null"))
(allow file-write* (literal "/dev/tty"))
```

The actual paths are canonicalised before the profile is generated. Nested roots are collapsed--if Tau's log directory is already beneath its configuration directory, only the parent rule is emitted.

### Writable locations

A sandboxed run may write to:

* The directory where Tau starts, or the directory explicitly selected with `--cwd`.
* Tau's resolved configuration directory (`TAU_HOME` or its platform default).
* Tau's resolved log directory (`TAU_LOGS_DIR` or its platform default).
* The active temporary directory returned by Python, normally derived from `$TMPDIR`.
* `/dev/null` and `/dev/tty`, which are required for ordinary CLI and terminal behaviour.

Everything else is read-only from Tau's perspective, subject to the permissions of the macOS user running it.

### Reads, networking and execution

The profile does not deny reads, outbound network access or process creation. Providers therefore retain network access, and coding tools can run shell commands, Python, tests, compilers and other local executables.

Those child processes inherit the Seatbelt profile. A command launched through the shell can write inside the selected project or the other permitted roots, but it cannot use a grandchild process to write elsewhere.

This is not a confidentiality sandbox: Tau and its tools may still read files that the current macOS user can read. Its purpose is to prevent accidental or model-directed modification outside the working set.

## Selecting the writable project

Without an explicit working directory, the directory containing the initial `tau` invocation is writable:

```sh
cd ~/Projects/example
tau
```

`--cwd` selects both the coding-tool working directory and the writable project root:

```sh
tau --cwd ~/Projects/example
```

The selected directory must already exist. Symlinks are resolved before the path is placed in the profile.

## Failure behaviour

Sandboxing is mandatory by default on macOS. Tau exits with status 1 rather than continuing without protection when:

* `/usr/bin/sandbox-exec` is absent or not executable.
* The selected working directory does not exist.
* Tau cannot prepare an allowed configuration, log or temporary directory.
* The `tau` executable cannot be resolved.
* Re-execution through `os.execve()` fails.

The error points to `--no-sandbox`, but Tau never selects that fallback automatically.

## Explicit override

Use `--no-sandbox` only when unrestricted filesystem writes are intentional:

```sh
tau --no-sandbox
```

The option has no practical effect on a-Shell, Linux or other non-macOS platforms because they do not enter this sandbox path.

## Apple API status

`/usr/bin/sandbox-exec` uses macOS Seatbelt profiles. Apple has deprecated the command but still ships it with current macOS releases. Tau Prime checks for the executable on every unsandboxed macOS startup and treats its absence as an error.

A future macOS release may require a different implementation. Keeping the sandbox bootstrap in `src/tau_coding/macos_sandbox.py` isolates that platform dependency from `AgentHarness`, `CodingSession`, provider clients and the TUI.

## Implementation and tests

The implementation is split across:

* `src/tau_coding/macos_sandbox.py` for platform detection, profile generation, path reduction and re-execution.
* `src/tau_coding/cli.py` for the default-on policy, `--no-sandbox` and fatal error reporting.
* `tests/test_macos_sandbox.py` for profile, path, guard and re-execution behaviour.
* `tests/test_cli.py` for default failure and explicit opt-out behaviour.

Run the automated checks with:

```sh
python -m pytest -q tests/test_macos_sandbox.py tests/test_cli.py
python -m compileall -q src tests
git diff --check
```

The profile generator and CLI integration are covered on non-macOS test hosts. Actual Seatbelt enforcement still requires a smoke test on macOS; the project does not claim that Linux tests exercise Apple's sandbox runtime.
