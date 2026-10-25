"""DriftPilot demo console — a local web page for presenting DriftPilot live.

    streamlit run demo/console/app.py

Not part of the product: DriftPilot itself runs as a GitHub Action. This page just drives the demo.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend  # noqa: E402

st.set_page_config(page_title="DriftPilot demo", page_icon="🧭", layout="wide")


@st.cache_resource
def credentials() -> dict[str, bool]:
    return backend.load_credentials()


checks = credentials()

# ---------- header + sidebar ----------
st.title("🧭 DriftPilot")
st.caption(
    "Catches hand-made changes to infrastructure, judges how much they matter, and proposes fixes "
    "that Terraform has proven correct. It runs as a GitHub Action; this page only drives the demo."
)

with st.sidebar:
    st.subheader("Ready?")
    for name, ok in checks.items():
        st.write(("✅ " if ok else "❌ ") + name)
    st.divider()
    st.markdown(
        f"**Links**\n\n"
        f"- [infra Actions runs](https://github.com/{backend.INFRA}/actions)\n"
        f"- [infra issues](https://github.com/{backend.INFRA}/issues)\n"
        f"- [infra pull requests](https://github.com/{backend.INFRA}/pulls)\n"
        f"- [demo-api branch protection](https://github.com/{backend.ORG}/demo-api/settings/branches)\n"
        f"- [Dashboard (real)]({backend.DASHBOARD})\n"
        f"- [Dashboard (simulated 90 days)]({backend.SIMULATED_DASHBOARD})"
    )


def follow_run(before_id: int | None) -> dict | None:
    """Show live progress of the DriftPilot run that GitHub starts by itself."""
    with st.status("Waiting for GitHub to start DriftPilot…", expanded=True) as status:
        for update in backend.follow_new_run(before_id):
            if update.phase == "waiting":
                status.update(label=f"Waiting for GitHub to start DriftPilot… {update.seconds}s")
            elif update.phase == "running":
                status.update(label=f"DriftPilot is running on GitHub… {update.seconds}s")
            elif update.phase == "done":
                ok = update.run["conclusion"] == "success"
                status.update(
                    label=f"Run finished ({update.run['event']}) in {update.seconds}s",
                    state="complete" if ok else "error",
                )
                st.markdown(f"[Open the run and its report on GitHub]({update.run['url']})")
                return update.run
            else:
                status.update(label="No run seen yet — check the Actions page", state="error")
    return None


def show_report(run: dict) -> None:
    lines = backend.run_report(run["databaseId"])
    if lines:
        st.code("\n".join(lines), language=None)


def show_items(since: datetime) -> None:
    items = backend.driftpilot_items(since)
    for issue in items["issues"]:
        with st.container(border=True):
            st.markdown(f"#### 🎫 Issue #{issue['number']}: [{issue['title']}]({issue['url']})")
            st.markdown(issue["body"].split("\n", 1)[1])  # drop the hidden marker line
    for pr in items["prs"]:
        with st.container(border=True):
            st.markdown(f"#### 🔀 Pull request #{pr['number']}: [{pr['title']}]({pr['url']})")
            st.code(backend.pr_diff(pr["number"]), language="diff")
            with st.expander("Description and Terraform proof"):
                st.markdown(pr["body"].split("\n", 1)[1])
    if not items["issues"] and not items["prs"]:
        st.info("No new DriftPilot issue or pull request yet.")


tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "1 · Dangerous change",
        "2 · Good change",
        "3 · On my laptop",
        "4 · History",
        "Reset",
    ]
)

# ---------- 1: dangerous change → critical issue ----------
with tab1:
    st.subheader("Someone removes the review requirement on `main`")
    st.markdown(
        "The Terraform code says `demo-api`'s `main` branch needs **2 approvals**. "
        "We change it to **0** by hand on GitHub, as someone might during a rush. "
        "Nobody presses anything after that: GitHub notices the change and starts DriftPilot, "
        "whose rulebook marks it **critical** and opens an issue with the fix."
    )
    c1, c2 = st.columns(2)
    if c1.button("🔓 Set approvals 2 → 0", type="primary", width="stretch"):
        since, before = datetime.now(UTC), backend.latest_run()
        backend.inject(2)
        st.success(
            f"Changed on GitHub — required approvals are now {backend.approvals_on_github()}."
        )
        run = follow_run(before["databaseId"] if before else None)
        if run:
            show_report(run)
            show_items(since)
    if c2.button("↩︎ Undo (back to 2 approvals)", width="stretch"):
        before = backend.latest_run()
        backend.revert(2)
        st.success(f"Restored — required approvals are now {backend.approvals_on_github()}.")
        run = follow_run(before["databaseId"] if before else None)
        if run:
            show_report(run)

# ---------- 2: good change → verified PR ----------
with tab2:
    st.subheader("An engineer adds a required check during an incident")
    st.markdown(
        "This change makes things *safer*, but the code doesn't know about it. "
        "No rule covers it, so DriftPilot asks the AI, which says **keep it**. "
        "DriftPilot then writes the code change, has "
        '**Terraform prove it** in a throwaway copy ("No changes"), and opens a pull request. '
        "A person decides whether to merge."
    )
    c1, c2 = st.columns(2)
    if c1.button("✅ Add a required status check", type="primary", width="stretch"):
        since, before = datetime.now(UTC), backend.latest_run()
        backend.inject(5)
        st.success("Changed on GitHub — `ci/hotfix-check` is now required on `main`.")
        run = follow_run(before["databaseId"] if before else None)
        if run:
            show_report(run)
            show_items(since)
    if c2.button("↩︎ Undo (remove the check)", width="stretch"):
        before = backend.latest_run()
        backend.revert(5)
        st.success("Removed.")
        run = follow_run(before["databaseId"] if before else None)
        if run:
            show_report(run)

# ---------- 3: the same engine on a laptop ----------
with tab3:
    st.subheader("The same engine, run directly (local Docker)")
    st.markdown(
        "DriftPilot is one program with two doors: GitHub runs it automatically; "
        "an engineer can run it by hand. "
        "Here it checks two Docker containers that Terraform manages on this laptop."
    )
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("🐳 Change memory 256 → 512 MB", width="stretch"):
        backend.inject(11)
        st.success("Container memory changed by hand.")
    if c2.button("🔍 Scan", type="primary", width="stretch"):
        with st.spinner("Asking Terraform what changed, then the rules and the AI…"):
            st.session_state["scan"] = backend.local_scan()
    if c3.button("🛠 Propose a fix", width="stretch"):
        result = st.session_state.get("scan") or backend.local_scan()
        with st.spinner("Writing the fix and having Terraform verify it…"):
            st.session_state["fix"] = backend.local_fix(result)
    if c4.button("↩︎ Undo", width="stretch"):
        backend.revert(11)
        st.session_state.pop("scan", None)
        st.session_state.pop("fix", None)
        st.success("Memory restored.")

    result = st.session_state.get("scan")
    if result is not None:
        rows = []
        for f in result.findings:
            v = result.verdicts.get(f.id)
            if v is not None and not v.is_real_drift:
                continue
            rows.append(
                {
                    "Severity": v.severity if v else "needs triage",
                    "Resource": f.address,
                    "Setting": f.attribute_path or "—",
                    "Change": f"{f.before} → {f.after}",
                    "Action": v.recommended_action if v else "—",
                    "Decided by": (v.rule_id or v.source) if v else "—",
                    "Why": v.reason if v else "",
                }
            )
        noise = len(result.findings) - len(rows)
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.success("No drift detected.")
        if noise:
            st.caption(f"{noise} noise finding(s) filtered by the rules.")

    for p in st.session_state.get("fix", []):
        with st.container(border=True):
            label = "✅ verified by Terraform" if p.verified else "not verified"
            st.markdown(f"#### Would open a {p.kind}: `{p.address}` ({p.action}) — {label}")
            for path, content in p.files.items():
                st.code(backend.unified_diff(path, content), language="diff")
            if p.proof:
                st.code(p.proof.splitlines()[0] if p.verified else p.proof, language=None)

# ---------- 4: history ----------
with tab4:
    st.subheader("What DriftPilot learns over time")
    st.markdown(
        "Every run is written to a history file. From it DriftPilot finds unusual days, "
        "settings that keep drifting, and whether people still agree with its suggestions. "
        "This dashboard uses 90 days of **simulated** history with planted patterns."
    )
    st.iframe(backend.SIMULATED_DASHBOARD, height=900)

# ---------- reset ----------
with tab5:
    st.subheader("Put everything back after the demo")
    if st.button("Undo all changes and close demo issues/PRs"):
        with st.spinner("Restoring…"):
            problems = []
            for scenario in (2, 5, 11):
                try:
                    backend.revert(scenario)
                except Exception as e:  # e.g. undoing something that was never changed
                    problems.append(f"scenario {scenario}: {e}")
            closed = backend.close_open_demo_items()
        st.success("Restored. Closed: " + (", ".join(closed) or "nothing was open"))
        for problem in problems:
            st.caption(f"Skipped {problem}")
        st.caption("Each undo also triggers a DriftPilot run on GitHub; it should say 'No drift'.")
