# CatchEtude local command endpoint

CatchEtude exposes a local inter-process communication (IPC) endpoint so another
process running on the same Windows machine can ask the application to enqueue
a file or scan a folder.

This is a Qt `QLocalServer` endpoint, **not an HTTP endpoint** and not a file
upload service. The sender passes a path that CatchEtude can access on the same
machine; the file bytes are not transferred over the socket.

## Connection

- Transport: Qt `QLocalSocket` / `QLocalServer`
- Server name: `CatchEtudeCommandServer`
- Message encoding: UTF-8
- Framing: one JSON object followed by a newline (`\\n`) per connection
- Response: one JSON object followed by a newline

The server must already be running. The endpoint is local to the machine where
CatchEtude is running.

## Enqueue a path

Send the `enqueue_path` command with an absolute path to either an existing
file or an existing directory.

### Request fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `cmd` | string | yes | Must be `enqueue_path`. |
| `path` | string | yes | Absolute path to one file or one directory. |
| `hide_secure` | boolean | no | Sets CatchEtude's Hide Secure option. Defaults to `true`. |

### Example: one file

```json
{"cmd":"enqueue_path","path":"C:/Users/Example/Downloads/image.png","hide_secure":true}
```

CatchEtude adds that file to the pending queue. Temporary files are rejected.

### Example: one folder

```json
{"cmd":"enqueue_path","path":"C:/Users/Example/Downloads/Incoming","hide_secure":false}
```

CatchEtude scans the directory recursively in the background and enqueues its
non-temporary files. The acknowledgement confirms that the folder request was
accepted and scheduled; it does not wait for the scan to finish.

### Successful response

A file request returns:

```json
{"ok":true,"accepted":true,"kind":"file","path":"C:/Users/Example/Downloads/image.png"}
```

A directory request returns the same shape with `"kind":"folder"`.

### Error response

Errors return `"ok":false` and an `error` code. Possible codes include:

- `invalid_json`: request is not a valid UTF-8 JSON object.
- `invalid_request`: request root is not a JSON object.
- `unknown_command`: command is not supported.
- `missing_path`: `path` is missing or empty.
- `path_not_found`: the supplied path does not exist.
- `invalid_path` or `unsupported_path`: the path cannot be resolved or is not a regular file/directory.
- `temporary_file`: a temporary file cannot be enqueued.
- `invalid_hide_secure`: `hide_secure` must be a JSON boolean.

## Use the provided client

The repository includes `send_command.py`, which connects to the endpoint,
sends the request, waits for the acknowledgement, and returns a non-zero exit
code when the request is rejected.

From PowerShell or CMD:

```powershell
python send_command.py "C:/Users/Example/Downloads/image.png" True
python send_command.py "C:/Users/Example/Downloads/Incoming" False
```

The first command enqueues only `image.png`. The second schedules a recursive
scan of the `Incoming` folder.

## Compatibility

For existing integrations, the server continues to accept the former payload
shape without a `cmd` property:

```json
{"path":"C:/Users/Example/Downloads/image.png","hide_secure":true}
```

Legacy clients that do not append a newline are processed when they close the
connection, but they do not receive an acknowledgement. New integrations
should use `cmd: "enqueue_path"`, append a newline, and read the JSON response.

The existing `capture_ui_render` command is also preserved.
