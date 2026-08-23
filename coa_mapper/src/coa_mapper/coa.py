from __future__ import annotations

from .models import CoaNode, Finding
from .normalize import significant_tokens


def structural_findings(nodes: list[CoaNode]) -> list[Finding]:
    findings: list[Finding] = []
    by_code = {n.account_code: n for n in nodes}
    children: dict[str, int] = {}
    for node in nodes:
        if node.parent_code:
            children[node.parent_code] = children.get(node.parent_code, 0) + 1

    for code in sorted(by_code):
        node = by_code[code]
        if not node.is_header and node.cf_category.upper() == "TBD":
            findings.append(
                Finding(
                    "COA_TBD_CATEGORY",
                    f"COA account {code} {node.account_name}: cash-flow category is TBD; "
                    f"blocks cash-flow statement only",
                    (code,),
                )
            )
        if node.is_header and children.get(code, 0) == 0 and node.statement == "BS":
            findings.append(
                Finding(
                    "COA_CHILDLESS_HEADER",
                    f"COA header {code} {node.account_name}: no children mapped; informational "
                    f"for BS/P&L rollup hygiene",
                    (code,),
                )
            )
        if not node.is_header and not node.parent_code:
            findings.append(
                Finding(
                    "COA_ROOT_LEAF",
                    f"COA account {code} {node.account_name}: leaf with no parent; sits outside "
                    f"the hierarchy",
                    (code,),
                )
            )
        if node.parent_code and node.parent_code not in by_code:
            findings.append(
                Finding(
                    "COA_PARENT_MISSING",
                    f"COA account {code} {node.account_name}: parent {node.parent_code} is not "
                    f"in the chart; this subtree is unreachable from any root",
                    (code, node.parent_code),
                )
            )

    findings.extend(_cycle_findings(by_code))
    return findings


def _cycle_findings(by_code: dict[str, CoaNode]) -> list[Finding]:
    """Report every parent cycle, once per cycle.

    The previous structural checks were all single-node (child counts, parentless
    leaves), so nothing ever walked a parent chain and a cycle was invisible. The
    mapper itself maps to leaves and never traverses, so it does not hang — but a
    cycle is fatal to the statement-stage rollup and must not pass silently.
    """
    findings: list[Finding] = []
    state: dict[str, int] = {}  # 0 = in progress on this walk, 1 = settled
    reported: set[frozenset[str]] = set()

    for start in sorted(by_code):
        if state.get(start) == 1:
            continue
        path: list[str] = []
        index: dict[str, int] = {}
        code: str | None = start
        while code is not None and state.get(code) != 1:
            if code in index:  # closed a loop within this walk
                cycle = path[index[code] :]
                key = frozenset(cycle)
                if key not in reported:
                    reported.add(key)
                    rotated = cycle[cycle.index(min(cycle)) :] + cycle[: cycle.index(min(cycle))]
                    findings.append(
                        Finding(
                            "COA_PARENT_CYCLE",
                            f"COA parent cycle: {' -> '.join(rotated + [rotated[0]])}; any rollup "
                            f"walking parent links recurses forever",
                            tuple(sorted(cycle)),
                        )
                    )
                break
            index[code] = len(path)
            path.append(code)
            state[code] = 0
            parent = by_code[code].parent_code
            code = parent if parent and parent in by_code else None
        for seen in path:
            state[seen] = 1
    return findings


def leaf_nodes(nodes: list[CoaNode]) -> list[CoaNode]:
    return [n for n in nodes if not n.is_header]


def token_index(nodes: list[CoaNode]) -> dict[str, frozenset[str]]:
    return {n.account_code: significant_tokens(n.account_name) for n in nodes}
