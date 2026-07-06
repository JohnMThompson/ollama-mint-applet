#!/usr/bin/env python3
import argparse
from pathlib import Path


def systemd_quote(value, *, expand_environment=False):
    escaped = []
    for character in str(value):
        if character == "\\":
            escaped.append("\\\\")
        elif character == '"':
            escaped.append('\\"')
        elif character == "\n":
            escaped.append("\\n")
        elif character == "\r":
            escaped.append("\\r")
        elif character == "\t":
            escaped.append("\\t")
        elif ord(character) < 32 or ord(character) == 127:
            escaped.append(f"\\x{ord(character):02x}")
        elif character == "%":
            escaped.append("%%")
        elif character == "$" and expand_environment:
            escaped.append("$$")
        else:
            escaped.append(character)
    return f'"{"".join(escaped)}"'


def systemd_path(value):
    escaped = []
    for byte in str(value).encode("utf-8"):
        character = chr(byte)
        if character.isascii() and (character.isalnum() or character in "/_.-"):
            escaped.append(character)
        elif character == "%":
            escaped.append("%%")
        else:
            escaped.append(f"\\x{byte:02x}")
    return "".join(escaped)


def render_unit(template, repository):
    repository = Path(repository).resolve()
    replacements = {
        "@WORKING_DIRECTORY@": systemd_path(repository),
        "@EXEC_START@": systemd_quote(
            repository / "scripts/run-llm-interface-service.sh",
            expand_environment=True,
        ),
    }
    rendered = template
    for marker, value in replacements.items():
        if rendered.count(marker) != 1:
            raise ValueError(f"unit template must contain exactly one {marker}")
        rendered = rendered.replace(marker, value)
    return rendered


def main():
    parser = argparse.ArgumentParser(description="Render the Local LLM Chat systemd unit")
    parser.add_argument("template", type=Path)
    parser.add_argument("repository", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rendered = render_unit(args.template.read_text(encoding="utf-8"), args.repository)
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
