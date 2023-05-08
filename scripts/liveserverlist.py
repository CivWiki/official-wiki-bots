from collections import defaultdict
from typing import Callable
from mwclient import Site
from mwclient.page import Page
from mwclient.listing import PageList
from datetime import datetime, timedelta
from os import getenv
from dataclasses import dataclass

# Load environment variables or use default values
DAYS_CUTOFF = int(getenv("DAYS_CUTOFF", "30"))
MINIMUM_EDITS_TO_BE_ACTIVE = int(getenv("MINIMUM_EDITS_TO_BE_ACTIVE", "1"))
LIVE_SERVERS_CATEGORY = getenv("LIVE_SERVERS_CATEGORY", "Live Servers")
INACTIVE_LIVE_SERVERS_CATEGORY = getenv(
    "INACTIVE_LIVE_SERVERS_CATEGORY", "Live Servers (Inactive)"
)
EXCLUSIONS = getenv(
    "EXCLUSIONS",
    "Civtoria3,Important non-civ servers,Template:Infobox server,List of civ servers in development",
).split(",")
SHOULD_EDIT_PAGES: bool = getenv("SHOULD_EDIT_PAGES", "True").lower() == "true"
USERNAME = getenv("USERNAME")
PASSWORD = getenv("PASSWORD")
# kind of hacky but I don't wanna spend more time on this feel free to make a pr improving this if it bothers you
LIVE_SERVERS = []
INACTIVE_SERVERS = []


@dataclass
class CategoryPageEdits:
    number_of_recent_edits: int = 0
    total_number_of_pages: int = 0


def get_category(site: Site, category_name: str) -> PageList | None:
    ### Helper function cause the default api has a type mismatch
    category: PageList | None = site.categories[category_name]  # type: ignore
    if not category.exists:  # type: ignore
        return None
    return category


def number_of_edits_in_last_x_days(x: int, page_name: str, site: Site) -> int:
    page: Page = site.pages[page_name]
    if not page.exists:  # Pages that don't exist have 0 edits
        return 0
    # Calculate the start timestamp (x days ago from the current date)
    cutoff_date = datetime.now() - timedelta(days=x)
    cutoff_timestamp = cutoff_date.strftime("%Y%m%d%H%M%S")
    # Get all the edits until the cutoff
    edits = page.revisions(end=cutoff_timestamp)
    return len(list(edits))


def category_number_of_edits_in_last_x_days(
    x: int, category_name: str, site: Site
) -> CategoryPageEdits:
    category = get_category(site, category_name)
    if category is None:  # When category doesn't exist, assume 0 edits
        return CategoryPageEdits(0, 0)
    total_edits = 0
    total_pages = 0
    for page in category:
        total_edits += number_of_edits_in_last_x_days(x, page.name, site)
        total_pages += 1
    return CategoryPageEdits(total_edits, total_pages)


def live_category_handler(
    amount_of_server_edits: int,
    active_category: str,
    inactive_category: str,
    minimum_required_edits: int,
    server_page: Page,
):
    if amount_of_server_edits < minimum_required_edits:
        page_content = server_page.text()
        page_content = page_content.replace(
            f"[[Category:{active_category}]]", f"[[Category:{inactive_category}]]"
        )
        server_page.edit(
            page_content,
            summary=f"Set the server as inactive due to the category not having any edits in the last {DAYS_CUTOFF} days.",
        )
        INACTIVE_SERVERS.append(server_page.name)


def inactive_category_handler(
    amount_of_server_edits: int,
    active_category: str,
    inactive_category: str,
    minimum_required_edits: int,
    server_page: Page,
):
    if amount_of_server_edits >= minimum_required_edits:
        page_content = server_page.text()
        page_content = page_content.replace(
            f"[[Category:{inactive_category}]]", f"[[Category:{active_category}]]"
        )
        server_page.edit(
            page_content,
            summary=f"Server {server_page.name} was previously inactive but now had {amount_of_server_edits} page edits.",
        )
        LIVE_SERVERS.append(server_page.name)
    else:
        print(
            f"Server {server_page.name} did not have enough required edits ({amount_of_server_edits}/{minimum_required_edits})"
        )


def process_server_categories(
    server_category: str,
    server_category_handler: Callable[[int, str, str, int, Page], None],
    days_cutoff: int = DAYS_CUTOFF,
    exclusions: list[str] = EXCLUSIONS,
    live_server_category: str = LIVE_SERVERS_CATEGORY,
    inactive_server_category: str = INACTIVE_LIVE_SERVERS_CATEGORY,
    minimum_required_edits: int = MINIMUM_EDITS_TO_BE_ACTIVE,
) -> dict[str, CategoryPageEdits]:
    print(f"Processing {server_category}")
    server_edits: defaultdict[str, CategoryPageEdits] = defaultdict(
        lambda: CategoryPageEdits(0, 0)
    )  # initialize dict with value 0
    # Fetch server categories
    server_categories = get_category(site, server_category)
    if server_categories is not None:
        for server_page in server_categories:
            if server_page.name in exclusions:  # Skip excluded servers
                continue
            server_edits_data = category_number_of_edits_in_last_x_days(
                days_cutoff, server_page.name, site
            )
            server_edits[server_page.name] = server_edits_data
            print(
                f"Found {server_edits_data.number_of_recent_edits} page edits for {server_page.name} with {server_edits_data.total_number_of_pages} total pages"
            )
            if SHOULD_EDIT_PAGES:
                server_category_handler(
                    server_edits_data.number_of_recent_edits,
                    live_server_category,
                    inactive_server_category,
                    minimum_required_edits,
                    server_page,
                )
    else:
        print(f"'Category:{server_category}' does not exist!")
    # Sort by page edits, if they are the same, highest total pages win
    return dict(
        sorted(
            server_edits.items(),
            key=lambda x: (x[1].number_of_recent_edits, -x[1].total_number_of_pages),
            reverse=True,
        )
    )

def write_live_server(page: str, edits: CategoryPageEdits) -> str:
    return f"* '''[[{page}]]''' - ''With '''{edits.number_of_recent_edits}''' page edits in the last {DAYS_CUTOFF} days and {edits.total_number_of_pages} pages in total''\n"

def write_inactive_server(page: str, edits: CategoryPageEdits) -> str:
    return f"* '''[[{page}]]''' - ''With {edits.number_of_recent_edits} page edits in the last {DAYS_CUTOFF} days and {edits.total_number_of_pages} pages in total''\n"

# Log in to wiki
if USERNAME is None or PASSWORD is None:
    raise Exception("Username and Password are not defined")

site: Site = Site(
    "civwiki.org", clients_useragent=f"LiveServerList/0.1 ({USERNAME.lower()}@civwiki)"
)
site.login(USERNAME, PASSWORD)

# Process inactive servers
inactive_servers = process_server_categories(
    INACTIVE_LIVE_SERVERS_CATEGORY, inactive_category_handler
)

# Process live servers
live_servers = process_server_categories(LIVE_SERVERS_CATEGORY, live_category_handler)

# Write the page
wikitext: str = "This page is a WIP and not fully working yet\n"
live_server_list = f"== Live Servers ==\n"
inactive_server_list = f"== Live Servers (Inactive) ==\n\n''Live Servers are considered inactive if they have had less than '''{MINIMUM_EDITS_TO_BE_ACTIVE}''' page edits in the last {DAYS_CUTOFF} days''\n"

for page, edits in live_servers.items():
    if page in INACTIVE_SERVERS:
        inactive_server_list += write_inactive_server(page, edits)
        continue
    live_server_list += write_live_server(page, edits)

for page, edits in inactive_servers.items():
    if page in LIVE_SERVERS:
        live_server_list += write_live_server(page, edits)
        continue
    # Write inactive server section
    inactive_server_list += write_inactive_server(page, edits)

wikitext += live_server_list
wikitext += inactive_server_list

# Print the page
print(wikitext)
test_page = site.pages["List of Civ Servers ordered by page edits"]
test_page.edit(wikitext, "Test live page should edit pages true")
