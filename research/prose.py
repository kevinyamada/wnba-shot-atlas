"""Keep generated research copy consistent without changing technical syntax."""
from __future__ import annotations
import re

# Preserve identities and executable text, including supplied player names.
_NAMES = ('Te-Hina', 'Hines-Allen', 'Cotta-Ortega', 'Courel-Ibáñez', 'scikit-learn')
_PROTECTED = re.compile(
    r'(^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\2[^\n]*(?:\n|$))'
    r'|(`+)([^`\n]*?)\3'
    r'|(!?\[[^\]\n]*\])\(([^\n]*?)\)'
    r'|(?:https?://|mailto:)[^\s<>]+'
    r'|</?[A-Za-z][A-Za-z0-9:-]*(?:\s+[^<>]*?)?/?>'
    r'|\b\d{4}-\d{2}-\d{2}\b', re.MULTILINE | re.DOTALL
)


def clean_text(text: str) -> str:
    """Normalize prose punctuation while retaining names and numeric signs."""
    saved = []
    def keep(value):
        saved.append(value)
        return f'\x00{len(saved)-1}\x00'
    for name in _NAMES:
        text = text.replace(name, keep(name))
    text = text.replace('SHA-256', 'SHA256')
    text = re.sub(r'(?m)(?<=\|)\s*—\s*(?=\|)', ' Not available ', text)
    if text.strip() == '—':
        text = text.replace('—', 'Not available')
    text = re.sub(r'\s*—\s*', ': ', text)
    text = re.sub(r'\s*–\s*', ' to ', text)
    text = re.sub(r'(?<=[A-Za-z0-9])-(?=[A-Za-z0-9])', ' ', text)
    text = re.sub(r'(?<=[)\]])-(?=[A-Za-z])', ' ', text)
    for i, value in enumerate(saved):
        text = text.replace(f'\x00{i}\x00', value)
    return text


def clean_markdown(text: str) -> str:
    """Clean visible copy while preserving code blocks, links and inline code."""
    chunks = []
    end = 0
    for match in _PROTECTED.finditer(text):
        chunks.append(clean_text(text[end:match.start()]))
        value = match.group()
        # A link's visible label is prose; its destination is left intact.
        if match.group(5) is not None:
            value = clean_text(match.group(5)) + '(' + match.group(6) + ')'
        chunks.append(value)
        end = match.end()
    chunks.append(clean_text(text[end:]))
    return ''.join(chunks)
