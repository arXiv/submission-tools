import typing
from multiprocessing.pool import ThreadPool
import re
from typing import Pattern

from .atomic import AtomicStringSet

# This triggers for .bbl as well
# r'^No file\s+(.*)\.$',

# make sure there is exactly one group catching the file name
TEX_LOG_ERRORS: typing.List[Pattern] = [
    re.compile(exp) for exp in [
        r'^\! LaTeX Error: File `([^\\\']*)\\\' not found\.',
        r'^\! I can\'t find file `([^\\\']*)\\\'\.',
        r'.*?:\d*: LaTeX Error: File `([^\\\']*)\\\' not found\.',
        r'^LaTeX Warning: File `([^\\\']*)\\\' not found',
        r'^Package .* [fF]ile `([^\\\']*)\\\' not found',
        r'^Package .* No file `([^\\\']*)\\\'',
        r'Error: pdflatex \(file ([^\)]*)\): cannot find image file',
        r': File `(.*)\' not found:\s*$',
        r'! Unable to load picture or PDF file \'([^\\\']+)\'.',
        r'Package pdftex.def Error: File (.*) not found: using draft setting\.',
        r'.*?:\d*: LaTeX Error:  Unknown graphics extension: (.*)\.',
    ]
]


def inspect_log(log: str,
                patterns: typing.List[Pattern] | None = None,
                break_on_found: bool = True) -> list[str]:
    """Run the list of regex against a blob string and count the matches.
    log: The log blob
    patterns: a list of regex patterns. default is TEX_LOG_ERRORS if not given.
    break_on_found: stop the search at first found
    """
    if patterns is None:
        patterns = TEX_LOG_ERRORS
    matched_results = AtomicStringSet()
    log_lines = log.splitlines()

    def _inspect(needle: re.Pattern) -> None:
        for line in log_lines:
            if (matched := needle.search(line)) is not None:
                matched_results.add(matched.group(1))
                if break_on_found:
                    break

    with ThreadPool(processes=len(patterns)) as pool:
        pool.map(_inspect, patterns)

    return list(matched_results.unguarded_value)


if __name__ == '__main__':
    print(inspect_log("\nNo file foo.\n"))
