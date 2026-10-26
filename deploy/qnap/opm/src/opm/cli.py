import argparse
import json
import re
import sys

from opm.client import OpenProjectClient, OpenProjectError
from opm.config import ConfigError, load_config

SUBJECT_WIDTH = 50
DURATION = re.compile(r"(?:(?P<h>\d+(?:[.,]\d+)?)\s*h)?\s*(?:(?P<m>\d+(?:[.,]\d+)?)\s*m)?")
BARE_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def main(argv: list[str] | None = None, client: OpenProjectClient | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "wp" and args.action == "set" and not changes_from(args):
        args.set_parser.error(
            "podaj przynajmniej jedną zmianę: --status, --assignee, --due, --start, --done, --subject, --description"
        )
    try:
        if client is None:
            config = load_config()
            client = OpenProjectClient(config.url, config.token)
        args.handler(client, args)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    except OpenProjectError as exc:
        print(f"Błąd: {exc.message}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    json_option = argparse.ArgumentParser(add_help=False)
    json_option.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help="wypisz wynik jako JSON"
    )

    parser = new_parser(description="Wiersz poleceń dla OpenProject.", prog="opm")
    parser.add_argument("--json", action="store_true", help="wypisz wynik jako JSON")
    commands = parser.add_subparsers(dest="command", metavar="POLECENIE", required=True)

    def command(name, help, handler, parent=commands):
        sub = parent.add_parser(name, help=help, description=help, parents=[json_option], add_help=False)
        add_help(sub)
        sub.set_defaults(handler=handler)
        return sub

    command("projects", "lista projektów", handle_projects)
    command("statuses", "lista statusów", handle_statuses)
    command("types", "lista typów zadań", handle_types)
    command("users", "lista użytkowników", handle_users)
    command("whoami", "kim jestem w OpenProject", handle_whoami)

    comment = command("comment", "dodaj komentarz do zadania", handle_comment)
    comment.add_argument("id", type=work_package_id, metavar="ID")
    comment.add_argument("text", metavar="TEKST")

    log_time = command("time", "zapisz czas pracy przy zadaniu", handle_time)
    log_time.add_argument("id", type=work_package_id, metavar="ID")
    log_time.add_argument(
        "hours", type=duration, metavar="GODZINY", help="np. 1.5h, 1,5h, 90m, 1h30m lub sama liczba godzin"
    )
    log_time.add_argument("--date", metavar="DATA", help="dzień pracy (RRRR-MM-DD), domyślnie dziś")
    log_time.add_argument("--comment", metavar="TEKST", help="komentarz do wpisu czasu")

    wp = command("wp", "zadania (work packages)", None)
    actions = wp.add_subparsers(dest="action", metavar="AKCJA", required=True)

    listing = command("list", "lista zadań", handle_wp_list, actions)
    listing.add_argument("-p", "--project", metavar="PROJEKT", help="identyfikator lub nazwa projektu")
    listing.add_argument("--mine", action="store_true", help="tylko zadania przypisane do mnie")
    listing.add_argument("--status", metavar="STATUS", help="nazwa statusu")
    listing.add_argument("--open", action="store_true", help="tylko otwarte zadania")
    listing.add_argument("-q", "--query", metavar="TEKST", help="szukaj w tytułach i opisach")

    show = command("show", "szczegóły zadania", handle_wp_show, actions)
    show.add_argument("id", type=work_package_id, metavar="ID")

    create = command("create", "utwórz zadanie", handle_wp_create, actions)
    create.add_argument("-p", "--project", required=True, metavar="PROJEKT", help="identyfikator lub nazwa projektu")
    create.add_argument("subject", metavar="TYTUŁ")
    create.add_argument("--type", metavar="TYP", help="nazwa typu zadania")
    create.add_argument("--assignee", metavar="UŻYTKOWNIK", help="nazwa, login lub 'me'")
    create.add_argument("--due", metavar="DATA", help="termin (RRRR-MM-DD)")
    create.add_argument("--start", metavar="DATA", help="data rozpoczęcia (RRRR-MM-DD)")
    create.add_argument("--description", metavar="TEKST", help="opis zadania")

    update = command("set", "zmień zadanie", handle_wp_set, actions)
    update.set_defaults(set_parser=update)
    update.add_argument("id", type=work_package_id, metavar="ID")
    update.add_argument("--status", metavar="STATUS", help="nazwa statusu")
    update.add_argument("--assignee", metavar="UŻYTKOWNIK", help="nazwa, login lub 'me'")
    update.add_argument("--due", metavar="DATA", help="termin (RRRR-MM-DD)")
    update.add_argument("--start", metavar="DATA", help="data rozpoczęcia (RRRR-MM-DD)")
    update.add_argument("--done", type=percent, metavar="N", help="postęp w procentach (0-100)")
    update.add_argument("--subject", metavar="TYTUŁ", help="nowy tytuł")
    update.add_argument("--description", metavar="TEKST", help="nowy opis")

    return parser


def new_parser(**kwargs) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False, **kwargs)
    add_help(parser)
    return parser


def add_help(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="pokaż pomoc i zakończ")


def work_package_id(value: str) -> int:
    try:
        return int(value.lstrip("#"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"niepoprawny numer zadania: {value!r}") from None


def percent(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"oczekiwano liczby całkowitej 0-100, otrzymano {value!r}") from None
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError(f"wartość spoza zakresu 0-100: {number}")
    return number


def duration(value: str) -> float:
    text = value.strip().lower()
    if BARE_NUMBER.fullmatch(text):
        hours = number(text)
    else:
        match = DURATION.fullmatch(text)
        if not match or not (match["h"] or match["m"]):
            raise argparse.ArgumentTypeError(
                f"niepoprawny czas {value!r}; użyj np. 1.5h, 1,5h, 90m, 1h30m lub samej liczby godzin"
            )
        hours = number(match["h"] or "0") + number(match["m"] or "0") / 60
    if hours <= 0:
        raise argparse.ArgumentTypeError(f"czas musi być dodatni, otrzymano {value!r}")
    return hours


def number(text: str) -> float:
    return float(text.replace(",", "."))


def changes_from(args: argparse.Namespace) -> dict:
    mapping = {
        "status": args.status,
        "assignee": args.assignee,
        "due_date": args.due,
        "start_date": args.start,
        "percent_done": args.done,
        "subject": args.subject,
        "description": args.description,
    }
    return {key: value for key, value in mapping.items() if value is not None}


def handle_projects(client, args):
    projects = client.list_projects()
    if args.json:
        return emit_json(projects)
    print_table(
        ["ID", "IDENTYFIKATOR", "NAZWA"],
        [[p["id"], p["identifier"], p["name"]] for p in projects],
    )


def handle_statuses(client, args):
    statuses = client.list_statuses()
    if args.json:
        return emit_json(statuses)
    print_table(
        ["ID", "NAZWA", "ZAMKNIĘTY"],
        [[s["id"], s["name"], "tak" if s.get("isClosed") else "nie"] for s in statuses],
    )


def handle_types(client, args):
    types = client.list_types()
    if args.json:
        return emit_json(types)
    print_table(["ID", "NAZWA"], [[t["id"], t["name"]] for t in types])


def handle_users(client, args):
    users = client.list_users()
    if args.json:
        return emit_json(users)
    print_table(
        ["ID", "NAZWA", "LOGIN", "E-MAIL"],
        [[u["id"], u["name"], u["login"], u["email"]] for u in users],
    )


def handle_whoami(client, args):
    me = client.whoami()
    if args.json:
        return emit_json(me)
    print(f"{me['name']} ({dash(me.get('login'))}), {dash(me.get('email'))}, #{me['id']}")


def handle_wp_list(client, args):
    work_packages = client.search_work_packages(
        project=args.project,
        assignee_me=args.mine,
        status=args.status,
        open_only=args.open,
        query=args.query,
    )
    if args.json:
        return emit_json(work_packages)
    print_table(
        ["ID", "STATUS", "TYTUŁ", "PRZYPISANY", "TERMIN"],
        [
            [wp["id"], wp["status"], truncate(wp["subject"]), wp["assignee"], wp["dueDate"]]
            for wp in work_packages
        ],
    )


def handle_wp_show(client, args):
    wp = client.get_work_package(args.id)
    if args.json:
        return emit_json(wp)
    fields = [
        ("Projekt", wp["project"]),
        ("Typ", wp["type"]),
        ("Status", wp["status"]),
        ("Przypisany", wp["assignee"]),
        ("Start", wp["startDate"]),
        ("Termin", wp["dueDate"]),
        ("Postęp", None if wp["percentageDone"] is None else f"{wp['percentageDone']}%"),
    ]
    print(f"#{wp['id']} {wp['subject']}")
    for label, value in fields:
        print(f"{label + ':':<12}{dash(value)}")
    print(f"{'URL:':<12}{wp['url']}")
    if wp.get("description"):
        print()
        print(wp["description"])


def handle_wp_create(client, args):
    wp = client.create_work_package(
        args.project,
        args.subject,
        type=args.type,
        assignee=args.assignee,
        description=args.description,
        start_date=args.start,
        due_date=args.due,
    )
    if args.json:
        return emit_json(wp)
    print(f"Utworzono #{wp['id']}: {wp['subject']}\n{wp['url']}")


def handle_wp_set(client, args):
    wp = client.update_work_package(args.id, **changes_from(args))
    if args.json:
        return emit_json(wp)
    print(f"Zaktualizowano #{wp['id']}: {wp['subject']}\n{wp['url']}")


def handle_comment(client, args):
    activity = client.add_comment(args.id, args.text)
    if args.json:
        return emit_json(activity)
    print(f"Dodano komentarz do #{args.id}")


def handle_time(client, args):
    entry = client.log_time(args.id, args.hours, date=args.date, comment=args.comment)
    if args.json:
        return emit_json(entry)
    print(f"Zapisano czas {args.hours:g} h przy #{args.id} ({entry['spentOn']})")


def emit_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def print_table(headers: list[str], rows: list[list]) -> None:
    cells = [[dash(value) for value in row] for row in rows]
    widths = [max(len(text) for text in column) for column in zip(headers, *cells)]
    for line in [headers, *cells]:
        print("  ".join(text.ljust(width) for text, width in zip(line, widths)).rstrip())


def truncate(text: str | None, width: int = SUBJECT_WIDTH) -> str | None:
    if text is None or len(text) <= width:
        return text
    return text[: width - 1] + "…"


def dash(value) -> str:
    return "-" if value is None or value == "" else str(value)
