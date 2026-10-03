"""xcmd: send commands to the editor that is already running and print the replies.

    python xcmd.py "GetProject"                      one command
    python xcmd.py "Close -Save 0" "OpenLevel -Level 0166FAE5EB82F3F3 -Save 0"      several, one per argument, in order
    python xcmd.py -t 300 "Play"                     a longer wait for the reply (seconds)
    python xcmd.py -                                 commands from stdin, one per line

No editor is started or stopped and none of the test harness' guards apply: this is the pipe, as the editor's own commands see it. Start an editor that stays up with live.py.
"""
import sys

from harness import DEFAULT_EXE, Editor


def main(argv) -> int:
    timeout = 30.0
    args = list(argv)
    if args[:1] == ["-t"] and len(args) > 2:
        timeout, args = float(args[1]), args[2:]
    lines = [l.rstrip("\r\n") for l in sys.stdin if l.strip()] if args == ["-"] else args
    if not lines:
        print(__doc__)
        return 2
    editor = Editor(DEFAULT_EXE)
    for line in lines:
        try:
            reply = editor._roundtrip(line, timeout)
        except (OSError, TimeoutError) as e:
            print(f"{line}\n  !! {e}")
            return 1
        print(reply.rstrip() if len(lines) == 1 else f"> {line}\n{reply.rstrip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
