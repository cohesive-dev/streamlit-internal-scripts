from clients.smartlead.index import (
    get_campaign_sequences,
    add_sequences_to_campaign,
    SmartleadCampaignSequenceInput,
    get_campaigns,
)
from bs4 import BeautifulSoup
import streamlit as st
import json
import base64
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from github import Github
from typing import List, Any
from datetime import datetime
from common.utils import get_gpt_answer
from common.spintax import validate_template


GITHUB_OWNER = "cohesive-dev"
GITHUB_REPO_NAME = "cohesive-ai-campaigns"
GITHUB_BRANCH = "main"
GITHUB_TOKEN = st.secrets.get("GITHUB_PAT_TOKEN", os.getenv("GITHUB_PAT_TOKEN"))


def get_github_repo():
    """Get the GitHub repository object."""
    if not GITHUB_TOKEN:
        st.error("GitHub token not found. Please set GITHUB_PAT_TOKEN in secrets.")
        return None

    g = Github(GITHUB_TOKEN)
    return g.get_repo(f"{GITHUB_OWNER}/{GITHUB_REPO_NAME}")


def check_campaign_file_exists(
    repo, campaign_id: int
) -> tuple[bool, dict | None, str | None]:
    """Check if campaign JSON file exists in the repository and return its content if exists."""
    path = f"{campaign_id}.json"

    try:
        file = repo.get_contents(path, ref=GITHUB_BRANCH)
        content = base64.b64decode(file.content).decode("utf-8")
        data = json.loads(content)
        return True, data, file.sha
    except Exception:
        return False, None, None


def build_campaign_json(
    campaign_id: int,
    sequences: List[Any],
    edited_variants: dict = None,
    edited_subjects: dict = None,
) -> str:
    """Build campaign JSON string from sequences."""
    campaign_data = {
        "campaign_id": campaign_id,
        "updated_at": datetime.now().isoformat(),
        "sequences": [],
    }

    for seq_idx, seq in enumerate(sequences):
        seq_data = {
            "id": seq.id,
            "seq_number": seq_idx + 1,
            "subject": seq.subject,
            "email_body": seq.email_body,
            "seq_delay_details": (
                seq.seq_delay_details.dict() if seq.seq_delay_details else None
            ),
            "variants": [],
        }

        if seq.sequence_variants:
            for var_idx, variant in enumerate(seq.sequence_variants):
                key = get_variant_index(seq_idx, var_idx)
                # Use edited variant body if available
                email_body = (
                    edited_variants.get(key, variant.email_body)
                    if edited_variants
                    else variant.email_body
                )
                # Use edited subject if available
                subject = (
                    edited_subjects.get(key, variant.subject)
                    if edited_subjects
                    else variant.subject
                )

                variant_data = {
                    "id": variant.id,
                    "variant_label": variant.variant_label,
                    "subject": subject,
                    "email_body": email_body,
                    "variant_distribution_percentage": variant.variant_distribution_percentage,
                }
                seq_data["variants"].append(variant_data)

        campaign_data["sequences"].append(seq_data)

    return json.dumps(campaign_data, indent=2)


def commit_campaign_to_github(
    repo, campaign_id: int, content: str, commit_message: str, file_sha: str = None
) -> bool:
    """Commit campaign JSON to GitHub repository."""
    path = f"{campaign_id}.json"

    try:
        if file_sha:
            # Update existing file
            repo.update_file(
                path=path,
                message=commit_message,
                content=content,
                sha=file_sha,
                branch=GITHUB_BRANCH,
            )
        else:
            # Create new file
            repo.create_file(
                path=path, message=commit_message, content=content, branch=GITHUB_BRANCH
            )
        return True
    except Exception as e:
        st.error(f"Failed to commit template: {e}")
        return False


def html_to_text(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "lxml")

    for div in soup.find_all("div"):
        children = [
            c for c in div.children if getattr(c, "name", None) or str(c).strip()
        ]

        # Case 1: <div><br></div>
        if len(children) == 1 and getattr(children[0], "name", None) == "br":
            div.replace_with("\n")
            continue

        # Case 2: normal div → process <br> inside
        for br in div.find_all("br"):
            br.replace_with("\n")

        # Append newline for the div
        div.replace_with(div.get_text() + "\n")

    return soup.get_text()


def text_to_html(text_content: str) -> str:
    """Convert plain text to HTML, wrapping paragraphs in <div> tags and empty lines as <br>."""
    lines = text_content.split("\n")
    html_parts = []

    for line in lines:
        if line.strip() == "":
            # Empty line becomes <br>
            html_parts.append("<br>")
        else:
            # Non-empty line wrapped in <div>
            html_parts.append(f"<div>{line}</div>")

    return "".join(html_parts)


def has_variant_changed(original_text: str, edited_text: str) -> bool:
    """Check if the variant has been modified by comparing original and edited text."""
    return original_text.strip() != edited_text.strip()


def apply_gpt_editing(original_text: str, instruction: str) -> str:
    """Apply GPT editing to the email body based on user instruction."""
    system_prompt = (
        "Edit email content per user instructions. "
        "Preserve: spintax {option1|option2|option3}, line breaks, "
        "and system variables (%sender-firstname%, %sender-name%, etc.). "
        "Return only the edited text."
    )

    user_prompt = (
        f"Original text:\n\n{original_text}\n\nEdit instruction: {instruction}"
    )

    return get_gpt_answer(system_prompt, user_prompt)


def apply_gpt_subject_editing(original_subject: str, instruction: str) -> str:
    """Apply GPT editing to the subject line based on user instruction."""
    system_prompt = (
        "Edit the email subject line per user instructions. "
        "Preserve: spintax {option1|option2|option3} "
        "and system variables (%sender-firstname%, %sender-name%, etc.). "
        "Return only the edited subject line, nothing else."
    )

    user_prompt = (
        f"Original subject: {original_subject}\n\nEdit instruction: {instruction}"
    )

    return get_gpt_answer(system_prompt, user_prompt)


def index_to_letter(i: int) -> str:
    result = ""
    i += 1
    while i > 0:
        i, rem = divmod(i - 1, 26)
        result = chr(ord("A") + rem) + result
    return result


def get_variant_index(sequence_idx: int, variant_idx: int) -> str:
    return f"sequence {sequence_idx + 1}, variant {index_to_letter(variant_idx)}"


# Initialize session state
if "sequences" not in st.session_state:
    st.session_state.sequences = None
if "edited_variants" not in st.session_state:
    st.session_state.edited_variants = {}
if "edited_subjects" not in st.session_state:
    st.session_state.edited_subjects = {}
if "current_instruction" not in st.session_state:
    st.session_state.current_instruction = ""
if "file_sha" not in st.session_state:
    st.session_state.file_sha = None
if "github_repo" not in st.session_state:
    st.session_state.github_repo = None

st.title("Campaign Editor")

# Campaign ID input
campaigns = get_campaigns()
campaign_options = {c.name: c.id for c in campaigns}
selected_campaign_name = st.selectbox(
    "Select Campaign", options=list(campaign_options.keys())
)
campaign_id = campaign_options[selected_campaign_name]

# Load Campaign Button
if st.button("Load Campaign", type="primary"):
    with st.spinner("Loading campaign and checking edit history..."):
        # Initialize GitHub repo
        repo = get_github_repo()
        if repo:
            st.session_state.github_repo = repo

            # Load sequences
            sequences = get_campaign_sequences(campaign_id)
            if sequences:
                st.session_state.sequences = sequences

                # Check if file exists in repo
                file_exists, existing_data, file_sha = check_campaign_file_exists(
                    repo, campaign_id
                )
                st.session_state.file_sha = file_sha

                if not file_exists:
                    st.info(
                        f"Campaign file {campaign_id}.json not found in repository. Creating initial commit..."
                    )
                    content = build_campaign_json(campaign_id, sequences)
                    if commit_campaign_to_github(
                        repo,
                        campaign_id,
                        content,
                        f"Initial commit for campaign {campaign_id}",
                    ):
                        st.success(
                            f"Created and committed {campaign_id}.json to repository"
                        )
                        # Get the new file SHA
                        _, _, new_sha = check_campaign_file_exists(repo, campaign_id)
                        st.session_state.file_sha = new_sha
                    else:
                        st.error("Failed to commit file to repository")
                else:
                    st.success(
                        f"Campaign loaded! File {campaign_id}.json already exists in repository."
                    )

                # Initialize edited variants and subjects storage
                st.session_state.edited_variants = {}
                st.session_state.edited_subjects = {}
                for seq_idx, seq in enumerate(sequences):
                    if seq.sequence_variants:
                        for var_idx, variant in enumerate(seq.sequence_variants):
                            key = get_variant_index(seq_idx, var_idx)
                            body_text = html_to_text(variant.email_body)
                            st.session_state.edited_variants[key] = body_text
                            st.session_state.edited_subjects[key] = variant.subject
                            # Also set widget keys so widgets read from session state
                            st.session_state[f"edited_{key}"] = body_text
                            st.session_state[f"edited_subject_{key}"] = variant.subject
            else:
                st.error("Failed to load campaign sequences")
        else:
            st.error("Failed to initialize GitHub repository")

# Show editor only if sequences are loaded
if st.session_state.sequences:
    st.divider()

    # Per-sequence instruction inputs
    st.subheader("Edit Instructions")
    st.caption(
        "Each sequence has its own prompts. Leave blank to skip editing that part."
    )

    seq_instructions = {}
    for seq_idx, seq in enumerate(st.session_state.sequences):
        seq_label = "Initial Email" if seq_idx == 0 else f"Follow-up {seq_idx}"
        with st.expander(
            f"**{seq_label}** (Sequence {seq_idx + 1})", expanded=(seq_idx == 0)
        ):
            subj_instr = st.text_input(
                "Subject line instruction:",
                placeholder='Example: Change subject to "Selling"',
                key=f"subject_instr_seq_{seq_idx + 1}",
            )
            body_instr = st.text_area(
                "Email body instruction:",
                placeholder="Example: Add more spintax, make tone more professional",
                key=f"body_instr_seq_{seq_idx + 1}",
            )
            seq_instructions[seq_idx + 1] = (subj_instr, body_instr)

    if st.button("Apply GPT Editing", type="primary"):
        has_any_instruction = any(s or b for s, b in seq_instructions.values())
        if not has_any_instruction:
            st.warning("Please enter at least one editing instruction")
        else:
            # Build a flat list of (key, original_body, original_subject, body_instr, subj_instr)
            # tasks for every variant that has at least one instruction.
            tasks = []
            for seq_idx, seq in enumerate(st.session_state.sequences):
                subj_instr, body_instr = seq_instructions.get(seq_idx + 1, (None, None))
                if not subj_instr and not body_instr:
                    continue
                if seq.sequence_variants:
                    for var_idx, variant in enumerate(seq.sequence_variants):
                        key = get_variant_index(seq_idx, var_idx)
                        tasks.append(
                            {
                                "key": key,
                                "original_body": html_to_text(variant.email_body),
                                "original_subject": variant.subject,
                                "body_instr": body_instr,
                                "subj_instr": subj_instr,
                            }
                        )

            if not tasks:
                st.warning("No variants found for sequences with instructions.")
            else:

                def _edit_variant(task: dict) -> dict:
                    """Run GPT edits for one variant. Safe to call from a thread."""
                    result = {"key": task["key"], "body": None, "subject": None}
                    if task["body_instr"]:
                        result["body"] = apply_gpt_editing(
                            task["original_body"], task["body_instr"]
                        )
                    if task["subj_instr"]:
                        result["subject"] = apply_gpt_subject_editing(
                            task["original_subject"], task["subj_instr"]
                        )
                    return result

                for t in tasks:
                    if t["body_instr"]:
                        st.toast(f"Editing body: {t['key']}")
                    if t["subj_instr"]:
                        st.toast(f"Editing subject: {t['key']}")

                with st.spinner(
                    f"Applying GPT editing to {len(tasks)} variant(s) of sequence  in parallel..."
                ):
                    with ThreadPoolExecutor(max_workers=min(len(tasks), 8)) as executor:
                        futures = {executor.submit(_edit_variant, t): t for t in tasks}
                        for future in as_completed(futures):
                            res = future.result()
                            key = res["key"]
                            if res["body"] is not None:
                                st.session_state.edited_variants[key] = res["body"]
                                st.session_state[f"edited_{key}"] = res["body"]
                            if res["subject"] is not None:
                                st.session_state.edited_subjects[key] = res["subject"]
                                st.session_state[f"edited_subject_{key}"] = res[
                                    "subject"
                                ]

                st.success(f"GPT editing applied to {len(tasks)} variant(s)!")
                st.rerun()

    st.divider()

    # Review variants
    st.subheader("Review and Edit Variants")

    for seq_idx, seq in enumerate(st.session_state.sequences):
        seq_label = "Initial Email" if seq_idx == 0 else f"Follow-up {seq_idx}"
        st.markdown(f"### {seq_label} (Sequence {seq_idx + 1})")
        st.markdown(f"**Subject:** {seq.subject}")

        if seq.sequence_variants:
            for var_idx, variant in enumerate(seq.sequence_variants):
                key = get_variant_index(seq_idx, var_idx)
                original_text = html_to_text(variant.email_body)
                edited_text = st.session_state.edited_variants.get(key, original_text)
                edited_subj = st.session_state.edited_subjects.get(key, variant.subject)
                is_changed = has_variant_changed(original_text, edited_text) or (
                    variant.subject.strip() != edited_subj.strip()
                )

                # Validate template
                validation_result = validate_template(edited_text)
                has_errors = not validation_result.get("ok", False)

                # Create expander label with change and error indicators
                change_indicator = "🔄 " if is_changed else ""
                error_indicator = "❌ " if has_errors else ""
                expander_label = f"{error_indicator}{change_indicator}Variant {index_to_letter(var_idx)} (ID: {variant.id})"

                with st.expander(
                    expander_label,
                    expanded=(var_idx == 0 or is_changed or has_errors),
                ):
                    # Show validation errors at the top
                    if has_errors:
                        error_msg = validation_result.get(
                            "error", "Unknown validation error"
                        )
                        error_context = validation_result.get("context", "")
                        error_position = validation_result.get("position", "")

                        context_html = ""
                        if error_context:
                            # Escape HTML and preserve formatting
                            escaped_context = (
                                error_context.replace("&", "&amp;")
                                .replace("<", "&lt;")
                                .replace(">", "&gt;")
                            )
                            context_html = f'<pre style="background-color: #2d2d2d; color: #f8f8f2; padding: 10px; border-radius: 4px; overflow-x: auto; font-family: monospace; font-size: 12px; margin-top: 8px;">{escaped_context}</pre>'

                        position_text = (
                            f" (position {error_position})"
                            if error_position != ""
                            else ""
                        )

                        st.markdown(
                            f'<div style="background-color: #f8d7da; color: #721c24; padding: 10px; border-radius: 4px; margin-bottom: 10px; border: 1px solid #f5c6cb;">'
                            f"❌ <strong>Template Validation Error:</strong> {error_msg}{position_text}"
                            f"{context_html}</div>",
                            unsafe_allow_html=True,
                        )

                    # Add visual highlight for changed variants
                    if is_changed:
                        st.markdown(
                            '<div style="background-color: #fff3cd; padding: 8px; border-radius: 4px; margin-bottom: 10px;">'
                            "⚠️ <strong>This variant has been modified</strong></div>",
                            unsafe_allow_html=True,
                        )
                    # Subject line editing
                    subj_col1, subj_col2 = st.columns(2)
                    with subj_col1:
                        st.markdown("**Original Subject**")
                        st.text_input(
                            "Original Subject",
                            value=variant.subject,
                            disabled=True,
                            key=f"original_subject_{key}",
                            label_visibility="collapsed",
                        )
                    with subj_col2:
                        st.markdown("**Edited Subject**")
                        edited_subject = st.text_input(
                            "Edited Subject",
                            key=f"edited_subject_{key}",
                            label_visibility="collapsed",
                        )
                        st.session_state.edited_subjects[key] = edited_subject

                    # Email body editing - Split view
                    col1, col2 = st.columns(2)

                    with col1:
                        st.markdown("**Before (Original)**")
                        st.text_area(
                            "Original",
                            value=original_text,
                            height=300,
                            disabled=True,
                            key=f"original_{key}",
                            label_visibility="collapsed",
                        )

                    with col2:
                        st.markdown("**After (Edited - Editable)**")
                        edited_text = st.text_area(
                            "Edited",
                            height=300,
                            key=f"edited_{key}",
                            label_visibility="collapsed",
                        )
                        st.session_state.edited_variants[key] = edited_text

        st.divider()

    # Commit section
    st.subheader("Commit Changes")
    commit_message = st.text_input(
        "Commit Message",
        placeholder=f"Update campaign {campaign_id} with [describe changes]",
        value=f"Update campaign {campaign_id}",
    )

    if st.button("Submit & Commit Changes", type="primary"):
        if not commit_message:
            st.error("Please enter a commit message")
        elif not st.session_state.github_repo:
            st.error("GitHub repository not initialized. Please reload the campaign.")
        else:
            with st.spinner("Saving and committing changes..."):
                # Build JSON content with edited variants and subjects
                content = build_campaign_json(
                    campaign_id,
                    st.session_state.sequences,
                    st.session_state.edited_variants,
                    st.session_state.edited_subjects,
                )

                # Commit to GitHub
                if commit_campaign_to_github(
                    st.session_state.github_repo,
                    campaign_id,
                    content,
                    commit_message,
                    st.session_state.file_sha,
                ):
                    st.success(
                        f"✅ Successfully committed changes to {GITHUB_OWNER}/{GITHUB_REPO_NAME}"
                    )

                    # Update Smartlead campaign with edited sequences
                    try:
                        input_sequences = []
                        for seq_idx, seq in enumerate(st.session_state.sequences):
                            seq_variants = None
                            if seq.sequence_variants:
                                seq_variants = []
                                for var_idx, variant in enumerate(
                                    seq.sequence_variants
                                ):
                                    key = get_variant_index(seq_idx, var_idx)
                                    edited_body = st.session_state.edited_variants.get(
                                        key, html_to_text(variant.email_body)
                                    )
                                    edited_subj = st.session_state.edited_subjects.get(
                                        key, variant.subject
                                    )
                                    seq_variants.append(
                                        {
                                            "id": variant.id,
                                            "subject": edited_subj,
                                            "email_body": text_to_html(edited_body),
                                            "variant_label": index_to_letter(var_idx),
                                            "variant_distribution_percentage": variant.variant_distribution_percentage,
                                        }
                                    )

                            input_sequences.append(
                                SmartleadCampaignSequenceInput(
                                    id=seq.id,
                                    seq_number=seq_idx + 1,
                                    subject=seq.subject,
                                    email_body=seq.email_body,
                                    seq_delay_details=(
                                        {
                                            "delay_in_days": seq.seq_delay_details.delayInDays
                                        }
                                        if seq.seq_delay_details
                                        else None
                                    ),
                                    seq_variants=seq_variants,
                                )
                            )

                        add_sequences_to_campaign(
                            campaign_id=campaign_id,
                            input_sequences=input_sequences,
                        )
                        st.success(
                            "✅ Successfully updated Smartlead campaign sequences"
                        )
                    except Exception as e:
                        st.error(f"Failed to update Smartlead campaign: {e}")

                    # Update the file SHA for future commits
                    _, _, new_sha = check_campaign_file_exists(
                        st.session_state.github_repo, campaign_id
                    )
                    st.session_state.file_sha = new_sha
                else:
                    st.error("Failed to commit changes")
