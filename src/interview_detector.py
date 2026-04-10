"""Detect company name and interview round from meeting subject/email."""
import re
import logging

logger = logging.getLogger(__name__)

# Common interview round patterns
ROUND_PATTERNS = [
    (r'round\s*(\d+)', 'Round {}'),
    (r'r(\d+)', 'Round {}'),
    (r'(\d+)(?:st|nd|rd|th)\s*round', 'Round {}'),
    (r'technical\s*(?:round|discussion|interview)', 'Technical'),
    (r'hr\s*(?:round|discussion|interview)', 'HR'),
    (r'managerial\s*(?:round|interview)', 'Managerial'),
    (r'coding\s*(?:round|test|challenge)', 'Coding'),
    (r'dsa\s*(?:round|test)', 'DSA'),
    (r'system\s*design', 'System Design'),
    (r'cultural?\s*fit', 'Cultural Fit'),
    (r'final\s*(?:round|interview)', 'Final'),
    (r'screening|phone\s*screen', 'Screening'),
    (r'intro(?:duction)?(?:\s*call)?', 'Intro'),
]

# Words to strip from company detection
STOP_WORDS = {
    'interview', 'discussion', 'meeting', 'call', 'round', 'technical',
    'with', 'for', 'the', 'and', 'confirmation', 'invite', 'scheduled',
    'your', 'our', 'team', 'hiring', 'recruitment', 'hr', 'test',
}


def detect_interview_info(subject: str, organizer: str = "") -> dict:
    """Parse meeting subject to extract company name and round.

    Returns: {"company": "HCL", "round": "Round 1", "folder_name": "HCL/Round_1"}
    """
    if not subject:
        return {"company": "Unknown", "round": "Interview", "folder_name": "Unknown/Interview"}

    subject_lower = subject.lower().strip()

    # Detect round
    round_name = "Interview"
    for pattern, template in ROUND_PATTERNS:
        match = re.search(pattern, subject_lower)
        if match:
            if '{}' in template:
                round_name = template.format(match.group(1))
            else:
                round_name = template
            break

    # Detect company - extract from subject by removing known patterns
    company = _extract_company(subject, organizer)

    # Build folder name
    folder_name = f"{_sanitize(company)}/{_sanitize(round_name)}"

    return {
        "company": company,
        "round": round_name,
        "folder_name": folder_name,
    }


def _extract_company(subject: str, organizer: str = "") -> str:
    """Extract company name from subject line."""
    # Try to find company name between common patterns
    # e.g., "Technical Discussion - HCL" or "HCL Round 1" or "Interview with Google"

    # Pattern: "Company_Name Round/Interview"
    # Remove round-related text
    cleaned = subject
    for pattern, _ in ROUND_PATTERNS:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    # Remove common separators and brackets
    cleaned = re.sub(r'[(\[\{].*?[)\]\}]', '', cleaned)  # Remove (parenthesized)
    cleaned = re.sub(r'[-\u2013\u2014_|/\\:,]', ' ', cleaned)  # Replace separators with space

    # Split into words and filter
    words = cleaned.split()
    company_words = []
    for w in words:
        w_clean = w.strip().lower()
        if w_clean and w_clean not in STOP_WORDS and len(w_clean) > 1:
            company_words.append(w.strip())

    if company_words:
        company = ' '.join(company_words[:3])  # Max 3 words for company name
        # Title case
        company = company.title()
    elif organizer:
        # Try extracting from organizer email domain
        match = re.search(r'@([\w.-]+)', organizer)
        if match:
            domain = match.group(1).split('.')[0]
            company = domain.title()
        else:
            company = "Unknown"
    else:
        company = "Unknown"

    return company


def _sanitize(name: str) -> str:
    """Make filesystem-safe."""
    return re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')[:50]
