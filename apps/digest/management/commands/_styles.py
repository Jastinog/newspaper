"""Shared ANSI formatting for digest CLI commands."""

BOLD = "\033[1m"
BLUE = "\033[1;34m"
GREEN = "\033[1;32m"
RED = "\033[1;31m"
YELLOW = "\033[1;33m"
CYAN = "\033[1;36m"
DIM = "\033[2m"
RESET = "\033[0m"


def arrow(msg):
    return f"{BLUE}::{BOLD} {msg}{RESET}"


def ok(msg):
    return f" {GREEN}[OK]{RESET} {msg}"


def fail(msg):
    return f" {RED}[FAIL]{RESET} {msg}"


def skip(msg):
    return f" {YELLOW}[SKIP]{RESET} {msg}"


def item(msg):
    return f" {DIM}->{RESET} {msg}"
