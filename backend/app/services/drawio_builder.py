"""Build draw.io (mxGraph) XML from a ProcessModel — valid, minimal, openable in diagrams.net."""

from __future__ import annotations

import html

from app.core.state import ProcessModel


def _a(value: str) -> str:
    return html.escape(value, quote=True)


def process_model_to_drawio_xml(model: ProcessModel) -> str:
    """Build a lane-aware process flow with start/end and decision branches."""
    title = (model.get("process_name") or "Process")[:200]
    steps = model.get("steps") or []
    decisions = model.get("decisions") or []
    roles = [str(r).strip() for r in (model.get("roles") or []) if str(r).strip()]
    if not roles:
        roles = list(dict.fromkeys(str(s.get("role") or "General").strip() for s in steps if isinstance(s, dict)))
    if not roles:
        roles = ["General"]

    parts: list[str] = []
    next_id = 2

    def alloc_id() -> str:
        nonlocal next_id
        out = str(next_id)
        next_id += 1
        return out

    parts.append(
        f'<mxCell id="{alloc_id()}" value="{_a(title)}" style="text;html=1;strokeColor=none;fillColor=none;'
        f'align=center;verticalAlign=middle;fontSize=14;fontStyle=1" vertex="1" parent="1">'
        f'<mxGeometry x="160" y="20" width="{max(360, len(roles) * 240)}" height="32" as="geometry"/></mxCell>'
    )

    if not steps:
        parts.append(
            f'<mxCell id="{alloc_id()}" value="No steps extracted — use numbered (1.) or bullet (-) lines in the instruction." '
            f'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;" vertex="1" parent="1">'
            f'<mxGeometry x="80" y="70" width="440" height="48" as="geometry"/></mxCell>'
        )
    else:
        lane_width = 260
        lane_x0 = 40
        y0 = 80
        role_x: dict[str, int] = {role: lane_x0 + idx * lane_width for idx, role in enumerate(roles)}
        role_palette = ["#e8f0fe", "#eaf7ea", "#fff7e6", "#f3e8ff", "#ffeef0"]

        # Lane containers
        for idx, role in enumerate(roles):
            x = role_x[role]
            lane_id = alloc_id()
            label_id = alloc_id()
            parts.append(
                f'<mxCell id="{lane_id}" value="" style="rounded=0;whiteSpace=wrap;html=1;'
                f'fillColor={role_palette[idx % len(role_palette)]};strokeColor=#c7c7c7;" vertex="1" parent="1">'
                f'<mxGeometry x="{x}" y="{y0}" width="{lane_width - 10}" height="980" as="geometry"/></mxCell>'
            )
            parts.append(
                f'<mxCell id="{label_id}" value="{_a(role)}" style="text;html=1;strokeColor=none;fillColor=none;'
                f'align=left;verticalAlign=middle;fontStyle=1;fontSize=12" vertex="1" parent="1">'
                f'<mxGeometry x="{x + 8}" y="{y0 + 6}" width="{lane_width - 20}" height="24" as="geometry"/></mxCell>'
            )

        # Start node
        start_id = alloc_id()
        parts.append(
            f'<mxCell id="{start_id}" value="Start" style="ellipse;whiteSpace=wrap;html=1;'
            f'fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">'
            f'<mxGeometry x="{lane_x0 + 80}" y="{y0 + 40}" width="90" height="42" as="geometry"/></mxCell>'
        )

        prev_node_id: str = start_id
        step_cell_by_step_id: dict[str, str] = {}
        step_pos: dict[str, tuple[int, int]] = {}

        for idx, st in enumerate(steps[:30]):
            role = (st.get("role") or roles[0]).strip()
            if role not in role_x:
                role = roles[0]
            nm = (st.get("name") or "Step").strip()[:300]
            step_id = str(st.get("id") or f"s{idx+1}")
            label = _a(nm)
            x = role_x[role] + 16
            y = y0 + 110 + idx * 90
            this = alloc_id()
            parts.append(
                f'<mxCell id="{this}" value="{label}" style="rounded=1;whiteSpace=wrap;html=1;'
                f'fillColor=#fff2cc;strokeColor=#d6b656;align=left;spacingLeft=8;" vertex="1" parent="1">'
                f'<mxGeometry x="{x}" y="{y}" width="{lane_width - 44}" height="52" as="geometry"/></mxCell>'
            )
            step_cell_by_step_id[step_id] = this
            step_pos[step_id] = (x, y)
            edge_id = alloc_id()
            parts.append(
                f'<mxCell id="{edge_id}" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;'
                f'jettySize=auto;html=1;endArrow=block;endFill=1;" edge="1" parent="1" '
                f'source="{prev_node_id}" target="{this}">'
                f'<mxGeometry relative="1" as="geometry"/></mxCell>'
            )
            prev_node_id = this

        # Decision nodes and branch edges.
        for idx, decision in enumerate(decisions[:8]):
            str(decision.get("id") or f"d{idx+1}")
            cond = (decision.get("condition") or "Decision").strip()[:180]
            true_path = [str(x) for x in (decision.get("true_path") or []) if str(x).strip()]
            false_path = [str(x) for x in (decision.get("false_path") or []) if str(x).strip()]
            anchor_step = true_path[0] if true_path else (false_path[0] if false_path else None)
            if anchor_step and anchor_step in step_pos:
                ax, ay = step_pos[anchor_step]
            else:
                ax, ay = (lane_x0 + 60, y0 + 220 + idx * 110)
            diamond_id = alloc_id()
            parts.append(
                f'<mxCell id="{diamond_id}" value="{_a(cond)}" style="rhombus;whiteSpace=wrap;html=1;'
                f'fillColor=#f8cecc;strokeColor=#b85450;" vertex="1" parent="1">'
                f'<mxGeometry x="{ax + 20}" y="{ay + 64}" width="120" height="80" as="geometry"/></mxCell>'
            )
            if anchor_step and anchor_step in step_cell_by_step_id:
                conn_id = alloc_id()
                parts.append(
                    f'<mxCell id="{conn_id}" style="edgeStyle=orthogonalEdgeStyle;rounded=0;jettySize=auto;html=1;'
                    f'endArrow=block;endFill=1;" edge="1" parent="1" source="{step_cell_by_step_id[anchor_step]}" target="{diamond_id}">'
                    f'<mxGeometry relative="1" as="geometry"/></mxCell>'
                )
            if true_path and true_path[0] in step_cell_by_step_id:
                t_edge = alloc_id()
                parts.append(
                    f'<mxCell id="{t_edge}" value="Yes" style="edgeStyle=orthogonalEdgeStyle;rounded=0;jettySize=auto;'
                    f'html=1;endArrow=block;endFill=1;" edge="1" parent="1" source="{diamond_id}" target="{step_cell_by_step_id[true_path[0]]}">'
                    f'<mxGeometry relative="1" as="geometry"/></mxCell>'
                )
            if false_path and false_path[0] in step_cell_by_step_id:
                f_edge = alloc_id()
                parts.append(
                    f'<mxCell id="{f_edge}" value="No" style="edgeStyle=orthogonalEdgeStyle;rounded=0;jettySize=auto;'
                    f'html=1;endArrow=block;endFill=1;" edge="1" parent="1" source="{diamond_id}" target="{step_cell_by_step_id[false_path[0]]}">'
                    f'<mxGeometry relative="1" as="geometry"/></mxCell>'
                )

        end_id = alloc_id()
        end_y = y0 + 150 + min(len(steps), 30) * 90
        parts.append(
            f'<mxCell id="{end_id}" value="End" style="ellipse;whiteSpace=wrap;html=1;'
            f'fillColor=#f8cecc;strokeColor=#b85450;" vertex="1" parent="1">'
            f'<mxGeometry x="{lane_x0 + 80}" y="{end_y}" width="90" height="42" as="geometry"/></mxCell>'
        )
        end_edge_id = alloc_id()
        parts.append(
            f'<mxCell id="{end_edge_id}" style="edgeStyle=orthogonalEdgeStyle;rounded=0;jettySize=auto;html=1;'
            f'endArrow=block;endFill=1;" edge="1" parent="1" source="{prev_node_id}" target="{end_id}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        )

        footer_id = alloc_id()
        parts.append(
            f'<mxCell id="{footer_id}" value="Generated by ProcessDoc — lanes/decisions can be fine-tuned in diagrams.net." '
            f'style="text;html=1;strokeColor=none;fillColor=none;align=left;fontSize=9;fontColor=#666666;" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="40" y="{end_y + 58}" width="860" height="20" as="geometry"/></mxCell>'
        )

    inner = "\n    ".join(parts)
    return (
        f'<mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" '
        f'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{max(850, len(roles) * 260 + 80)}" pageHeight="1400">\n'
        f'  <root>\n'
        f'    <mxCell id="0"/>\n'
        f'    <mxCell id="1" parent="0"/>\n'
        f'    {inner}\n'
        f'  </root>\n'
        f'</mxGraphModel>'
    )
