#!/usr/bin/env python3
"""
AcademiQ — Open Knowledge Format (OKF) Engine
Provides structured extraction of Knowledge Units (KUs), rules, conditions,
tables, section hierarchies, and metadata from documents.
"""

import os
import re
import json
import hashlib
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict

@dataclass
class RuleClause:
    """Represents an extracted condition-action-exception rule."""
    clause_id: str
    condition: str
    action: str
    threshold: Optional[str] = None
    exception: Optional[str] = None

@dataclass
class TableBlock:
    """Represents a structured table extracted from a document."""
    title: str
    headers: List[str]
    rows: List[List[str]]

@dataclass
class DocumentMetadata:
    """Metadata describing a document within the OKF framework."""
    title: str
    category: str
    authority: str
    version: str
    effective_date: Optional[str] = None
    expiry_date: Optional[str] = None
    file_hash: str = ""

@dataclass
class KnowledgeUnit:
    """
    A discrete, structured unit of knowledge adhering to the Open Knowledge Format.
    """
    unit_id: str
    parent_id: Optional[str]
    chunk_type: str                  # 'parent' or 'child'
    entity_type: str                 # 'policy', 'rule', 'table', 'procedure', 'faq', 'general'
    section_title: str
    content: str
    summary: str
    rules: List[Dict[str, Any]] = field(default_factory=list)
    table_data: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    page_number: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class OKFExtractor:
    """
    Parses raw text, markdown, HTML, or PDF extracts into structured OKF Knowledge Units.
    """

    CHILD_CHUNK_SIZE = 450
    CHILD_OVERLAP = 70
    PARENT_CHUNK_SIZE = 1800

    @staticmethod
    def compute_file_hash(content_bytes: bytes) -> str:
        return hashlib.sha256(content_bytes).hexdigest()

    @classmethod
    def extract_document_metadata(cls, text: str, filename: str) -> DocumentMetadata:
        """
        Infers document title, category, authority, and version from text headers and filename.
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        
        # 1. Infer Title
        title = filename
        for line in lines[:10]:
            # Look for markdown header or leading bold title
            m = re.match(r'^(?:#\s*|\*\*|)([A-Z0-9][\w\s\-\:,\.]{4,80})(?:\*\*|)$', line)
            if m and not line.lower().startswith("table of contents"):
                title = m.group(1).strip()
                break

        # 2. Infer Category
        category = "general"
        lower_text = text[:3000].lower()
        if any(k in lower_text for k in ["grading", "gpa", "grade point", "academic transcript"]):
            category = "grading_policy"
        elif any(k in lower_text for k in ["academic integrity", "plagiarism", "cheating", "honor code"]):
            category = "academic_integrity"
        elif any(k in lower_text for k in ["registration", "add/drop", "course withdrawal", "enrollment"]):
            category = "course_registration"
        elif any(k in lower_text for k in ["faculty", "office hours", "professor", "advisor"]):
            category = "faculty_directory"
        elif any(k in lower_text for k in ["credit risk", "loan", "underwriting", "ltv", "dscr", "aml", "kyc"]):
            category = "financial_compliance"
        elif any(k in lower_text for k in ["salary", "benefits", "leave policy", "severance", "hr"]):
            category = "human_resources"

        # 3. Infer Authority
        authority = "Institutional Authority"
        auth_patterns = [
            r"(?:Office of (?:the )?([A-Za-z\s]+))",
            r"(?:Approved by:?\s*([A-Za-z\s]+))",
            r"(?:Department of\s*([A-Za-z\s]+))",
            r"(?:Issued by:?\s*([A-Za-z\s]+))"
        ]
        for pat in auth_patterns:
            auth_match = re.search(pat, text[:2500], re.IGNORECASE)
            if auth_match:
                authority = auth_match.group(0).strip()
                break

        # 4. Infer Version
        version = "1.0"
        ver_match = re.search(r'\b(?:version|v|ver\.?)\s*([0-9]+(?:\.[0-9]+)*)', text[:2000], re.IGNORECASE)
        if ver_match:
            version = ver_match.group(1).strip()

        # 5. Dates
        effective_date = None
        date_match = re.search(r'(?:effective|valid from|date:)\s*([A-Za-z0-9,\s\-\/]{4,25})', text[:2000], re.IGNORECASE)
        if date_match:
            effective_date = date_match.group(1).strip()

        return DocumentMetadata(
            title=title,
            category=category,
            authority=authority,
            version=version,
            effective_date=effective_date
        )

    @classmethod
    def parse_markdown_tables(cls, text: str) -> List[TableBlock]:
        """Extract markdown-formatted tables into structured TableBlocks."""
        tables = []
        table_regex = re.compile(r'((?:\|[^\n]+\|\r?\n){2,})')
        matches = table_regex.finditer(text)
        
        for idx, match in enumerate(matches):
            raw_table = match.group(1).strip()
            lines = [l.strip() for l in raw_table.splitlines() if l.strip()]
            if len(lines) < 2:
                continue
            
            # Extract headers
            headers = [c.strip() for c in lines[0].strip('|').split('|')]
            # Check if second line is separator (e.g. |---|---|)
            start_row = 1
            if len(lines) > 1 and re.match(r'^\|?[\s\-:|]+\|?$', lines[1]):
                start_row = 2

            rows = []
            for r_line in lines[start_row:]:
                row_cells = [c.strip() for c in r_line.strip('|').split('|')]
                if any(row_cells):
                    rows.append(row_cells)

            if headers and rows:
                tables.append(TableBlock(
                    title=f"Extracted Table #{idx + 1}",
                    headers=headers,
                    rows=rows
                ))

        return tables

    @classmethod
    def extract_rules_and_clauses(cls, text: str) -> List[RuleClause]:
        """
        Identifies policy conditions, numerical thresholds, requirements, and penalties.
        """
        rules = []
        patterns = [
            r'(?:if|when|where)\s+([^,\.\n]{5,100}),?\s+(?:then\s+|shall\s+|must\s+|will\s+|results in\s+|is\s+)([^,\.\n]{5,120})',
            r'(?:minimum|maximum|requires|penalty for|threshold for)\s+([^:\n]{4,60}):?\s*([^\.\n]{5,100})',
            r'(?:clause|section|rule)\s+([0-9\.]+[a-z]?):?\s*([^\.\n]{10,120})'
        ]

        clause_num = 1
        for pat in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                cond = m.group(1).strip()
                action = m.group(2).strip()
                
                thresh_match = re.search(r'(\d+(?:\.\d+)?\s*(?:%|\$|GPA|days|weeks|months|credits|hours|points)?)', cond + " " + action)
                threshold = thresh_match.group(1) if thresh_match else None

                rules.append(RuleClause(
                    clause_id=f"rule_{clause_num}",
                    condition=cond,
                    action=action,
                    threshold=threshold
                ))
                clause_num += 1

        return rules[:10]

    @classmethod
    def split_into_sections(cls, text: str) -> List[Dict[str, Any]]:
        """
        Splits document into logical sections based on headers, clauses, or double-newlines.
        """
        KNOWN_HEADINGS = {
            'summary', 'education', 'skills', 'technical skills', 'programming & analytics',
            'projects', 'key projects', 'experience', 'work experience', 'positions of responsibility',
            'leadership', 'achievements & certifications', 'certifications', 'coursework',
            'contact', 'overview', 'scope', 'purpose', 'policy', 'guidelines', 'regulations',
            'grading policy', 'definitions', 'penalties', 'appeals', 'office hours'
        }

        lines = text.splitlines()
        splits = []
        current_title = "Overview"
        current_buf = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_buf:
                    current_buf.append("")
                continue

            # Check if line is a section heading
            is_heading = False
            heading_title = stripped

            if stripped.lower() in KNOWN_HEADINGS:
                is_heading = True
            elif stripped.startswith("#"):
                is_heading = True
                heading_title = stripped.lstrip("#").strip()
            elif re.match(r'^(?:[0-9]+\.\s+|Section\s+[0-9A-Z\.]+:|[A-Z\s0-9\.\-]{3,40}:)$', stripped):
                is_heading = True
                heading_title = stripped.rstrip(":").strip()
            elif len(stripped) < 40 and stripped.isupper() and len(stripped) > 3:
                is_heading = True

            if is_heading:
                content = "\n".join(current_buf).strip()
                if len(content) > 20:
                    splits.append({"title": current_title, "content": content})
                current_title = heading_title
                current_buf = []
            else:
                current_buf.append(line)

        content = "\n".join(current_buf).strip()
        if len(content) > 10:
            splits.append({"title": current_title, "content": content})

        if not splits:
            splits = [{"title": "General", "content": text.strip()}]

        return splits

    @classmethod
    def generate_contextual_prefix(cls, doc_title: str, sec_title: str, category: str, authority: str, parent_content: str, chunk_text: str) -> str:
        """
        Generates a rich contextual prefix situating the chunk within the document/section.
        """
        cat_formatted = category.replace('_', ' ').title()
        return f"[{doc_title} > {sec_title} | {authority} | {cat_formatted}]\n{chunk_text}"

    @classmethod
    def process_document(cls, text: str, filename: str) -> List[KnowledgeUnit]:
        """
        End-to-end extraction creating Parent and Child Knowledge Units.
        """
        metadata = cls.extract_document_metadata(text, filename)
        sections = cls.split_into_sections(text)
        
        all_units: List[KnowledgeUnit] = []

        for sec_idx, sec in enumerate(sections):
            sec_title = sec["title"]
            sec_content = sec["content"]

            tables = cls.parse_markdown_tables(sec_content)
            rules = cls.extract_rules_and_clauses(sec_content)

            entity_type = "general"
            if tables:
                entity_type = "table"
            elif rules:
                entity_type = "rule"
            elif any(k in sec_title.lower() for k in ["policy", "guideline", "regulation"]):
                entity_type = "policy"
            elif any(k in sec_title.lower() for k in ["faq", "frequently asked", "q&a"]):
                entity_type = "faq"

            # 1. Parent Knowledge Unit
            parent_unit_id = f"ku_p_{sec_idx + 1}"
            parent_summary = sec_content[:200].replace("\n", " ").strip() + "..."
            
            table_dict = None
            if tables:
                table_dict = {
                    "headers": tables[0].headers,
                    "rows": tables[0].rows
                }

            parent_unit = KnowledgeUnit(
                unit_id=parent_unit_id,
                parent_id=None,
                chunk_type="parent",
                entity_type=entity_type,
                section_title=sec_title,
                content=sec_content,
                summary=parent_summary,
                rules=[asdict(r) for r in rules],
                table_data=table_dict,
                metadata={
                    "doc_title": metadata.title,
                    "category": metadata.category,
                    "authority": metadata.authority,
                    "version": metadata.version
                }
            )
            all_units.append(parent_unit)

            # 2. Child Units
            child_chunks = cls._chunk_string(sec_content, cls.CHILD_CHUNK_SIZE, cls.CHILD_OVERLAP)
            for c_idx, chunk_text in enumerate(child_chunks):
                child_unit_id = f"ku_c_{sec_idx + 1}_{c_idx + 1}"
                contextual_content = cls.generate_contextual_prefix(
                    metadata.title, sec_title, metadata.category, metadata.authority, sec_content, chunk_text
                )

                child_unit = KnowledgeUnit(
                    unit_id=child_unit_id,
                    parent_id=parent_unit_id,
                    chunk_type="child",
                    entity_type=entity_type,
                    section_title=sec_title,
                    content=contextual_content,
                    summary=chunk_text[:120].replace("\n", " ").strip(),
                    rules=[asdict(r) for r in rules],
                    table_data=table_dict,
                    metadata={
                        "doc_title": metadata.title,
                        "category": metadata.category,
                        "authority": metadata.authority,
                        "version": metadata.version,
                        "parent_id": parent_unit_id
                    }
                )
                all_units.append(child_unit)

        return all_units

    @staticmethod
    def _chunk_string(text: str, size: int, overlap: int) -> List[str]:
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        chunks = []
        start = 0
        while start < len(text):
            end = start + size
            if end < len(text):
                for sep in ["\n\n", ". ", "\n", " "]:
                    idx = text.rfind(sep, start, end)
                    if idx != -1 and idx > start + overlap:
                        end = idx + len(sep)
                        break
            chunk = text[start:end].strip()
            if len(chunk) >= 30:
                chunks.append(chunk)
            start = end - overlap
        return chunks if chunks else [text]
