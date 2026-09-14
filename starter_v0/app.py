from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from chat import now_iso, run_model_tool_loop, safe_slug, trim_history, write_transcript
from providers import make_provider
from tools import load_tool_declarations, to_openai_tools
from versioning import artifact_version_dict, build_artifact_version


ROOT = Path(__file__).parent
SYSTEM_PROMPT_PATH = ROOT / 'artifacts' / 'system_prompt.md'
TOOLS_PATH = ROOT / 'artifacts' / 'tools.yaml'
TRANSCRIPTS_DIR = ROOT / 'transcripts'
PROVIDER_NAME = 'openrouter'
HISTORY_WINDOW = 5
MAX_TOOL_ROUNDS = 4


def new_transcript(version: str, model: str, artifact: Any) -> tuple[dict[str, Any], Path]:
    timestamp = datetime.now().strftime('%Y%m%dT%H%M%S%f')
    transcript_id = '_'.join([safe_slug(version), PROVIDER_NAME, timestamp])
    path = TRANSCRIPTS_DIR / f'{transcript_id}.transcript.json'
    transcript = {
        'transcript_id': transcript_id,
        **artifact_version_dict(artifact),
        'provider': PROVIDER_NAME,
        'model': model,
        'system_prompt': str(SYSTEM_PROMPT_PATH),
        'tools': str(TOOLS_PATH),
        'history_window': HISTORY_WINDOW,
        'max_tool_rounds': MAX_TOOL_ROUNDS,
        'created_at': now_iso(),
        'updated_at': now_iso(),
        'turns': [],
    }
    return transcript, path


def reset_conversation(config: tuple[str, str]) -> None:
    st.session_state.chat_config = config
    st.session_state.history = []
    st.session_state.ui_messages = []
    st.session_state.transcript = None
    st.session_state.transcript_path = None


def render_trace(rounds: list[dict[str, Any]]) -> None:
    expanded = any(item.get('tool_calls') for item in rounds)
    with st.expander('Tool trace', expanded=expanded):
        for item in rounds:
            st.write('Round', item['round'])
            if item.get('assistant_text'):
                st.caption(item['assistant_text'])
            if not item.get('tool_calls'):
                st.caption('No tool call.')
            for call in item.get('tool_calls', []):
                st.code(call['name'], language=None)
                st.json(call.get('args', {}))
            for event in item.get('tool_results', []):
                result = event.get('result')
                if isinstance(result, dict) and result.get('error'):
                    st.error(event['tool'] + ': ' + str(result['error']))
                st.json(event)


def main() -> None:
    st.set_page_config(page_title='IT Helpdesk Agent', page_icon='🛠️', layout='wide')
    st.title('IT Helpdesk Agent')
    st.caption('Live Chat UI · OpenRouter · transparent tool trace')

    provider = make_provider(PROVIDER_NAME)
    default_model = getattr(provider, 'default_model', 'openai/gpt-4o-mini')
    version = st.sidebar.text_input('Artifact version', value='v0').strip() or 'v0'
    model = st.sidebar.text_input('OpenRouter model', value=default_model).strip() or default_model
    artifact = build_artifact_version(version, SYSTEM_PROMPT_PATH, TOOLS_PATH)
    config = (artifact.artifact_version, model)

    if 'chat_config' not in st.session_state or st.session_state.chat_config != config:
        reset_conversation(config)
    if st.sidebar.button('New conversation', use_container_width=True):
        reset_conversation(config)

    st.sidebar.subheader('Runtime')
    st.sidebar.write('Provider: ' + PROVIDER_NAME)
    st.sidebar.write('Model: ' + model)
    st.sidebar.subheader('Artifact version')
    st.sidebar.code(artifact.artifact_version, language=None)
    with st.sidebar.expander('Full SHA-256 hashes'):
        st.code(f'prompt: {artifact.prompt_hash}\ntools:  {artifact.tools_hash}', language=None)

    transcript_path = st.session_state.transcript_path
    st.sidebar.subheader('Transcript')
    st.sidebar.code(str(transcript_path) if transcript_path else 'Created after the first message', language=None)

    if not os.getenv('OPENROUTER_API_KEY'):
        st.warning('Missing OPENROUTER_API_KEY in .env; the UI opens, but messages cannot be sent yet.')

    for message in st.session_state.ui_messages:
        with st.chat_message(message['role']):
            st.markdown(message['content'])
            if message.get('rounds'):
                render_trace(message['rounds'])

    user_text = st.chat_input('Describe your IT issue')
    if not user_text:
        return

    st.session_state.ui_messages.append({'role': 'user', 'content': user_text})
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding='utf-8')
    tools = to_openai_tools(load_tool_declarations(TOOLS_PATH))
    messages = [
        {'role': 'system', 'content': system_prompt},
        *trim_history(st.session_state.history, HISTORY_WINDOW),
        {'role': 'user', 'content': user_text},
    ]

    if st.session_state.transcript is None:
        transcript, path = new_transcript(version, model, artifact)
        st.session_state.transcript = transcript
        st.session_state.transcript_path = path

    turn = {
        'turn_index': len(st.session_state.transcript['turns']) + 1,
        'started_at': now_iso(),
        'user': user_text,
        'status': 'started',
        'assistant_text': None,
        'rounds': [],
        'tool_events': [],
    }

    try:
        with st.spinner('Agent is working...'):
            result = run_model_tool_loop(
                provider=provider,
                messages=messages,
                tools=tools,
                model=model,
                max_tool_rounds=MAX_TOOL_ROUNDS,
            )
        turn.update(result)
        assistant_text = result['assistant_text']
        st.session_state.history.extend([
            {'role': 'user', 'content': user_text},
            {'role': 'assistant', 'content': assistant_text},
        ])
        st.session_state.ui_messages.append({
            'role': 'assistant',
            'content': assistant_text,
            'rounds': result['rounds'],
        })
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
        turn.update({'status': 'provider_error', 'error': error})
        st.session_state.ui_messages.append({'role': 'assistant', 'content': 'ERROR: ' + error})

    turn['ended_at'] = now_iso()
    st.session_state.transcript['turns'].append(turn)
    write_transcript(st.session_state.transcript_path, st.session_state.transcript)
    st.rerun()


if __name__ == '__main__':
    main()
