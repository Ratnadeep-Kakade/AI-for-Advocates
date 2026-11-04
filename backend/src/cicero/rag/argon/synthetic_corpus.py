"""
Module 2: Synthetic Corporate Legal Corpus Generator (PDF & DOCX)
Generates realistic corporate legal agreements for testing the Argon Legal RAG pipeline:
1. DOC_001: Series A Preferred Shareholders Agreement (US Letter 612x792 pt, PDF & DOCX)
   - Includes multi-block split headings/lead-ins to test LogicalUnitReconstructor.
   - Includes diverse cross-reference styles ('Subject to Section 5.1', 'Sub-clause (b) of Clause 4.2',
     'As provided under Article 7', 'In accordance with Schedule I', 'Clause 4.2(b)(ii)').
   - Includes 3 structured tables (T_001 Capitalization Table, T_002 Milestone Payment Schedule,
     T_003 14-row Detailed Vesting Schedule).
2. DOC_002: Master Services and Technology License Agreement (ISO A4 595.28x841.89 pt, PDF)
   - Uses A4 page dimensions to verify dynamic page dimension extraction.
   - Contains distinct definitions of 'Affiliate' and 'Confidential Information' and an ambiguous
     cross-reference ('Subject to Clause (a)') to test AMBIGUOUS reference detection.
3. DOC_999: Unstructured/Malformed Legal Note (tests deterministic hierarchy validation failure & fallback).
4. DOC_998: Un-OCR'd Blank/Scanned Page PDF (tests PARTIALLY_PROCESSED / FAILED OCR status handling).
"""

import os
from typing import Dict, Any, List
from reportlab.lib.pagesizes import LETTER, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab import rl_config
rl_config.invariant = 1
import docx


SHAREHOLDERS_AGREEMENT_BLOCKS: List[Dict[str, Any]] = [
    {"page": 1, "text": "SERIES A PREFERRED SHAREHOLDERS AGREEMENT"},
    {"page": 1, "text": "This Series A Preferred Shareholders Agreement (this \"Agreement\") is entered into on this Execution Date of 10 November 2025, and shall become legally binding on the Effective Date of 14 November 2025, by and among Argon Quantum Systems, Inc., a Delaware corporation (the \"Company\"), the key founders listed on Schedule 1 (hereinafter referred to as \"Founders\"), and the Series A Investors."},
    # Split heading across two blocks on Page 1 to test LogicalUnitReconstructor:
    {"page": 1, "text": "ARTICLE I"},
    {"page": 1, "text": "DEFINITIONS AND INTERPRETATION"},
    {"page": 1, "text": "1.1 Defined Terms. For purposes of this Agreement, the following capitalized terms shall have the specific meanings set forth below:"},
    {"page": 1, "text": "(a) \"Affiliate\" means any entity that directly or indirectly controls, is controlled by, or is under common control with the Company, where control denotes beneficial ownership of more than fifty percent (50%) of the voting securities of such entity."},
    {"page": 1, "text": "(b) \"Material Adverse Effect\" shall mean any event, change, circumstance, or occurrence that, individually or in the aggregate, has a material adverse effect on the financial condition, intellectual property assets, or business operations of the Company, costing in excess of USD $2,500,000."},
    {"page": 1, "text": "(c) \"Confidential Information\" means all non-public proprietary algorithms, quantum circuit designs, customer lists, source code, and financial models disclosed by the Company to any Shareholder."},
    {"page": 2, "text": "(d) \"Cause\" shall mean with respect to any Founder: (i) willful misconduct or gross negligence in the performance of duties; (ii) conviction of a felony involving fraud or embezzlement; or (iii) a material breach of Article V (Confidentiality) that remains uncured for fifteen (15) days."},
    {"page": 2, "text": "(e) \"Change of Control\" means any merger, consolidation, or sale of all or substantially all of the assets of the Company in which the Shareholders immediately prior to such transaction hold less than fifty percent (50%) of the voting power immediately following such transaction."},
    {"page": 2, "text": "(f) \"Liquidation Preference\" shall mean an amount equal to 1.5x the Original Issue Price of USD $25.00 per Series A Preferred Share, plus any declared but unpaid dividends."},
    {"page": 2, "text": "(g) \"Permitted Transferee\" means any Affiliate of an Investor or any family trust established for the exclusive benefit of a Founder's immediate family."},
    {"page": 2, "text": "(h) \"Supermajority Approval\" shall mean the affirmative written consent of Shareholders holding at least seventy-five percent (75%) of the issued and outstanding Series A Preferred Shares."},
    {"page": 2, "text": "1.2 Accounting and Statutory References. All accounting terms not specifically defined herein shall be construed in accordance with U.S. GAAP, and corporate governance matters shall be construed pursuant to Section 144 of the Delaware General Corporation Law."},
    {"page": 3, "text": "ARTICLE II CAPITALIZATION AND SHAREHOLDING"},
    {"page": 3, "text": "2.1 Authorized Share Capital. The authorized capitalization of the Company as of the Effective Date is set forth in detail in Schedule 1 attached hereto and incorporated herein by reference."},
    {"page": 3, "text": "2.2 Pre-Emptive Rights. Subject to Section 5.1, each Major Investor shall have a pro-rata right of first offer to purchase its respective allotment of any New Securities proposed to be issued by the Company."},
    {"page": 3, "text": "2.3 Anti-Dilution Protection. In accordance with Schedule I, if the Company issues Additional Shares of Common Stock at a price below the Series A Original Issue Price, the conversion price of the Series A Preferred Shares shall be adjusted on a broad-based weighted average basis."},
    {"page": 4, "text": "ARTICLE III CORPORATE GOVERNANCE AND BOARD PROTECTIVE PROVISIONS"},
    {"page": 4, "text": "3.1 Board Composition. The Board of Directors of the Company shall consist of five (5) directors: two (2) appointed by Founder A and Founder B, two (2) appointed by Investor C and Horizon Ventures LP, and one (1) independent industry director mutually selected by the Board."},
    {"page": 4, "text": "3.2 Protective Provisions. Notwithstanding Section 3.1, the Company shall not, without first obtaining Supermajority Approval: (a) alter or change the rights, preferences, or privileges of the Series A Preferred Shares; (b) authorize or issue any equity security senior to or on parity with the Series A Preferred Shares; or (c) consummate any Change of Control transaction."},
    {"page": 5, "text": "ARTICLE IV INDEMNIFICATION AND LIMITATION OF LIABILITY"},
    {"page": 5, "text": "4.1 General Indemnification by the Company and Founders. The Company and the Founders shall jointly and severally indemnify, defend, and hold harmless each Series A Investor and its Affiliates from and against any and all losses, damages, liabilities, and reasonable attorneys' fees arising out of any breach of representations, warranties, or covenants contained in this Agreement."},
    # Split section body and its lead-in across two blocks on Page 5 to test LogicalUnitReconstructor:
    {"page": 5, "text": "4.2 Contractual Liability Cap and Specific Exceptions. The aggregate liability of the Founders under this Agreement shall be strictly governed by the following limitations and carve-outs."},
    {"page": 5, "text": "The following exceptions apply:"},
    {"page": 5, "text": "(a) Standard Warranty Cap. Subject to Section 5.1, the cumulative liability of any Founder for breaches of standard operational representations shall not exceed fifty percent (50%) of the gross cash proceeds actually received by such Founder."},
    {"page": 5, "text": "(b) Fraud, Willful Misconduct, and Core IP Carve-Out. Notwithstanding Section 4.1 and Clause 4.2(a), the total liability of the Founders shall not be capped at the Standard Warranty Cap, and shall extend up to one hundred percent (100%) of the aggregate Series A Investment Amount (USD $12,000,000), if the claim arises from:"},
    {"page": 5, "text": "(i) intentional fraud, criminal misrepresentation, or willful misconduct committed by a Founder in connection with the transaction; or"},
    {"page": 5, "text": "(ii) any fundamental breach of Intellectual Property ownership warranties causing a Material Adverse Effect, including undisclosed open-source copyleft contamination under the GNU Affero General Public License:"},
    {"page": 5, "text": "(A) where such contamination requires public disclosure of the Company's core quantum error-correction compiler; or"},
    {"page": 5, "text": "(B) where a third-party injunction halts commercial licensing of the Argon QPU firmware for more than thirty (30) consecutive days."},
    {"page": 6, "text": "(c) Basket Threshold. No Indemnified Party shall be entitled to recover damages under Section 4.1 or Sub-clause (b) of Clause 4.2 unless and until the aggregate indemnifiable losses exceed a deductible basket of USD $100,000, as provided under Article 7."},
    {"page": 6, "text": "ARTICLE V CONFIDENTIALITY, NON-COMPETITION AND TRANSFER RESTRICTIONS"},
    {"page": 6, "text": "5.1 Lock-Up and Transfer Restrictions. No Founder shall sell, assign, pledge, encumber, or otherwise transfer any Founder Shares prior to the third (3rd) anniversary of the Effective Date without prior Supermajority Approval, except for transfers to a Permitted Transferee."},
    {"page": 6, "text": "5.2 Protection of Confidential Information. Each Shareholder shall maintain all Confidential Information in strict confidence and shall not disclose such Confidential Information to any third party, except to its legal, tax, and financial advisors bound by professional duties of confidentiality."},
    {"page": 6, "text": "5.3 Non-Competition Covenant. During the period in which a Founder holds any equity in the Company and for eighteen (18) months thereafter, such Founder shall not directly or indirectly engage in any competing fault-tolerant quantum computing business."},
    {"page": 7, "text": "ARTICLE VI TERM, TERMINATION AND SURVIVAL"},
    {"page": 7, "text": "6.1 Term and Expiration. This Agreement shall commence on the Effective Date of 14 November 2025 and, unless terminated earlier in accordance with this Article VI, shall remain in full force until the initial Financing Covenant Expiration Date of 15 November 2026."},
    {"page": 7, "text": "6.2 Termination Events. This Agreement may be terminated solely upon: (a) the written consent of the Company and Shareholders holding Supermajority Approval; (b) the consummation of a qualified Initial Public Offering generating gross proceeds of at least USD $75,000,000; or (c) an uncured material breach following a formal Cure Notice Date occurring Thirty (30) days after the Effective Date."},
    {"page": 7, "text": "6.3 Survival and Prior Amendments. Notwithstanding Section 6.1, the provisions of Article IV (Indemnification) and Section 5.2 (Confidentiality) shall survive any termination of this Agreement for a period of five (5) years. A prior preliminary side letter was recorded with an Amendment Date of 03/04/2026."},
    {"page": 8, "text": "ARTICLE VII DISPUTE RESOLUTION AND GOVERNING LAW"},
    {"page": 8, "text": "7.1 Governing Law. This Agreement and all claims arising hereunder shall be governed by and construed in accordance with the internal laws of the State of Delaware, without regard to conflict of law principles, and deferred compensation matters shall comply with Section 409A of the Internal Revenue Code."},
    {"page": 8, "text": "7.2 Binding Arbitration and Escrow Holdback. Any dispute arising under Article IV, Clause 4.2(b)(ii), or Annexure A shall be resolved by binding arbitration in Wilmington, Delaware under the Commercial Arbitration Rules of the American Arbitration Association."},
    {"page": 9, "text": "Schedule 1 Capitalization Table and Shareholding Schedule"},
    {"page": 9, "text": "The following Capitalization Table sets forth the complete issued and outstanding equity ownership of Argon Quantum Systems, Inc. immediately following the Series A Closing:"},
    {"page": 10, "text": "Annexure A Escrow Release, Milestone Payment Schedule and Vesting Tranches"},
    {"page": 10, "text": "In accordance with Section 4.2 and Section 7.2, the Series A Investor tranches and Founder vesting tranches shall be released strictly in accordance with the following schedules:"},
]

SHAREHOLDERS_TABLES: List[Dict[str, Any]] = [
    {
        "table_id": "T_001",
        "document_id": "DOC_001",
        "caption": "Capitalization Table",
        "headers": ["Shareholder", "Share Class", "Shares", "Ownership", "Invested Capital (USD)"],
        "rows": [
            ["Founder A", "Common Stock", "10000", "50%", "500000"],
            ["Founder B", "Common Stock", "6000", "30%", "300000"],
            ["Investor C", "Series A Preferred", "2500", "12.5%", "7500000"],
            ["Horizon Ventures LP", "Series A Preferred", "1000", "5.0%", "3000000"],
            ["Employee Option Pool", "Common Options", "500", "2.5%", "1500000"],
        ],
        "page": 9,
        "parent_node_id": "N_DOC_001_Schedule_1",
    },
    {
        "table_id": "T_002",
        "document_id": "DOC_001",
        "caption": "Milestone Payment and Escrow Schedule",
        "headers": ["Milestone ID", "Deliverable Description", "Target Date", "Release Amount (USD)", "Holdback Percentage"],
        "rows": [
            ["MS-01", "Execution & Initial Closing Tranche", "2025-11-14", "6000000", "10%"],
            ["MS-02", "64-Qubit Cryogenic Array Verification", "2026-03-31", "3000000", "10%"],
            ["MS-03", "Fault-Tolerant Logical Gate Benchmark", "2026-08-15", "2000000", "15%"],
            ["MS-04", "Commercial Cloud API General Availability", "2026-11-15", "1000000", "20%"],
        ],
        "page": 10,
        "parent_node_id": "N_DOC_001_Annexure_A",
    },
    {
        "table_id": "T_003",
        "document_id": "DOC_001",
        "caption": "Founder and Executive Detailed Quarterly Vesting Tranche Schedule",
        "headers": ["Tranche ID", "Beneficiary", "Quarter", "Vesting Date", "Vested Shares", "Cumulative Vested"],
        "rows": [
            ["VT-01", "Founder A", "Q1-2026", "2026-02-14", "1250", "1250"],
            ["VT-02", "Founder A", "Q2-2026", "2026-05-14", "1250", "2500"],
            ["VT-03", "Founder A", "Q3-2026", "2026-08-14", "1250", "3750"],
            ["VT-04", "Founder A", "Q4-2026", "2026-11-14", "1250", "5000"],
            ["VT-05", "Founder A", "Q1-2027", "2027-02-14", "1250", "6250"],
            ["VT-06", "Founder A", "Q2-2027", "2027-05-14", "1250", "7500"],
            ["VT-07", "Founder A", "Q3-2027", "2027-08-14", "1250", "8750"],
            ["VT-08", "Founder A", "Q4-2027", "2027-11-14", "1250", "10000"],
            ["VT-09", "Founder B", "Q1-2026", "2026-02-14", "750", "750"],
            ["VT-10", "Founder B", "Q2-2026", "2026-05-14", "750", "1500"],
            ["VT-11", "Founder B", "Q3-2026", "2026-08-14", "750", "2250"],
            ["VT-12", "Founder B", "Q4-2026", "2026-11-14", "750", "3000"],
            ["VT-13", "Founder B", "Q1-2027", "2027-02-14", "1500", "4500"],
            ["VT-14", "Founder B", "Q2-2027", "2027-05-14", "1500", "6000"],
        ],
        "page": 10,
        "parent_node_id": "N_DOC_001_Annexure_A",
    },
]

MSA_BLOCKS: List[Dict[str, Any]] = [
    {"page": 1, "text": "MASTER SERVICES AND TECHNOLOGY LICENSE AGREEMENT"},
    {"page": 1, "text": "This Master Services and Technology License Agreement (this \"MSA\") is executed on the Execution Date of 01 December 2025 and effective as of the Effective Date of 05 December 2025, between Argon Quantum Systems, Inc. (the \"Provider\") and Nexus Cloud Infrastructure LLC (the \"Customer\")."},
    {"page": 1, "text": "ARTICLE I DEFINITIONS"},
    {"page": 1, "text": "1.1 Defined Terms. In this MSA:"},
    {"page": 1, "text": "(a) \"Affiliate\" means any wholly-owned subsidiary of Customer where Customer holds one hundred percent (100%) of the voting equity and operational control."},
    {"page": 1, "text": "(b) \"Confidential Information\" shall mean only tangible written materials explicitly stamped 'CONFIDENTIAL - NEXUS CLOUD' at the time of disclosure."},
    {"page": 1, "text": "(c) \"Service Level Availability\" means a monthly uptime percentage of at least 99.95% for the hosted Quantum Simulation Cluster."},
    {"page": 2, "text": "ARTICLE IV INDEMNIFICATION AND LIABILITY"},
    {"page": 2, "text": "4.1 Provider IP Indemnification. Provider shall defend and indemnify Customer against third-party patent or copyright infringement claims directly caused by Customer's authorized use of the Argon Quantum SDK."},
    {"page": 2, "text": "4.2 Limitation of Liability. Subject to Section 4.1, neither party's aggregate liability under this MSA shall exceed twelve (12) months of SaaS subscription fees paid by Customer (USD $480,000):"},
    {"page": 2, "text": "(a) Direct Damages Only. Neither party shall be liable for indirect or consequential damages."},
    {"page": 3, "text": "ARTICLE VI TERM AND TERMINATION"},
    {"page": 3, "text": "6.1 Initial Term and Q4 2026 Expiration. This MSA shall commence on 05 December 2025 and shall automatically expire on the Expiration Date of 15 December 2026 unless renewed in writing by both parties."},
    {"page": 3, "text": "6.2 Termination for Convenience and Cure Period. Unlike equity agreements requiring Supermajority Approval, either party may terminate this MSA for convenience upon sixty (60) days prior written notice, or immediately upon an uncured material breach after thirty (30) days written notice."},
]

MSA_TABLES: List[Dict[str, Any]] = [
    {
        "table_id": "T_DOC002_001",
        "document_id": "DOC_002",
        "caption": "Cloud QPU Service Tier and Fee Schedule",
        "headers": ["Tier Name", "Monthly QPU Hours", "Monthly Fee (USD)", "SLA Credit Cap"],
        "rows": [
            ["Enterprise Silver", "200", "15000", "10%"],
            ["Enterprise Gold", "500", "25000", "25%"],
            ["Dedicated Cryo Node", "2000", "40000", "50%"],
        ],
        "page": 3,
        "parent_node_id": "N_DOC_002_6_2",
    }
]

MALFORMED_BLOCKS: List[Dict[str, Any]] = [
    {"page": 1, "text": "UNSTRUCTURED DRAFT SIDE LETTER MEMORANDUM"},
    {"page": 1, "text": "This informal side memo discusses preliminary thoughts on quantum hardware procurement without standard legal numbering."},
    {"page": 1, "text": "(b) Orphan sub-clause appearing without any parent section or article header before it."},
    {"page": 1, "text": "9.4.2 Jump to deep subsection without Section 9 or 9.4 existing anywhere in the document."},
    {"page": 2, "text": "(ii) Another dangling roman numeral subclause discussing miscellaneous laboratory equipment delivery schedules."},
]


def _render_pdf(filepath: str, blocks: List[Dict[str, Any]], tables: List[Dict[str, Any]], pagesize=LETTER) -> None:
    """Renders blocks and tables into a multi-page PDF with specified pagesize (LETTER or A4)."""
    doc = SimpleDocTemplate(filepath, pagesize=pagesize, leftMargin=54, rightMargin=54, topMargin=54, bottomMargin=54, invariant=1)
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "LegalBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        spaceAfter=8,
    )
    title_style = ParagraphStyle(
        "LegalTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        spaceAfter=12,
    )

    story = []
    current_page = 1
    tables_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for t in tables:
        tables_by_page.setdefault(t["page"], []).append(t)

    for idx, b in enumerate(blocks):
        if b["page"] > current_page:
            for tbl in tables_by_page.get(current_page, []):
                story.append(Spacer(1, 8))
                story.append(Paragraph(f"<b>{tbl['caption']}</b>", body_style))
                data = [tbl["headers"]] + tbl["rows"]
                rl_table = Table(data, hAlign="LEFT")
                rl_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A60")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F9")]),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                ]))
                story.append(rl_table)
                story.append(Spacer(1, 10))
            story.append(PageBreak())
            current_page = b["page"]

        txt = b["text"].replace("&", "&amp;")
        if idx == 0 or txt.startswith("ARTICLE ") or txt.startswith("Schedule ") or txt.startswith("Annexure "):
            story.append(Paragraph(f"<b>{txt}</b>", title_style if idx == 0 else body_style))
        else:
            story.append(Paragraph(txt, body_style))

    for tbl in tables_by_page.get(current_page, []):
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"<b>{tbl['caption']}</b>", body_style))
        data = [tbl["headers"]] + tbl["rows"]
        rl_table = Table(data, hAlign="LEFT")
        rl_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A60")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F9")]),
        ]))
        story.append(rl_table)

    doc.build(story)


def _render_unocrd_scan_pdf(filepath: str) -> None:
    """Renders a 2-page PDF where Page 1 has digital text and Page 2 is an un-OCR'd vector graphic page with zero text layer."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(filepath, pagesize=A4, invariant=1)
    c.setFont("Helvetica", 11)
    c.drawString(72, 750, "PAGE 1: COVER PAGE FOR SCANNED EXHIBIT")
    c.drawString(72, 730, "1.1 Exhibit Overview. The following page is an un-OCR'd scanned image with no text layer.")
    c.showPage()
    # Page 2: Draw only graphical rectangles/lines (simulating a raster/scanned page without OCR text)
    c.rect(72, 200, 450, 500, stroke=1, fill=0)
    c.line(72, 650, 522, 650)
    c.showPage()
    c.save()


def _render_docx(filepath: str, blocks: List[Dict[str, Any]], tables: List[Dict[str, Any]]) -> None:
    """Renders blocks and tables into a Word DOCX file using python-docx."""
    d = docx.Document()
    tables_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for t in tables:
        tables_by_page.setdefault(t["page"], []).append(t)

    current_page = 1
    for idx, b in enumerate(blocks):
        if b["page"] > current_page:
            for tbl in tables_by_page.get(current_page, []):
                p = d.add_paragraph()
                p.add_run(tbl["caption"]).bold = True
                wt = d.add_table(rows=1, cols=len(tbl["headers"]))
                hdr_cells = wt.rows[0].cells
                for i, h in enumerate(tbl["headers"]):
                    hdr_cells[i].text = str(h)
                for row in tbl["rows"]:
                    rc = wt.add_row().cells
                    for i, val in enumerate(row):
                        rc[i].text = str(val)
            d.add_page_break()
            current_page = b["page"]

        d.add_paragraph(b["text"])

    for tbl in tables_by_page.get(current_page, []):
        p = d.add_paragraph()
        p.add_run(tbl["caption"]).bold = True
        wt = d.add_table(rows=1, cols=len(tbl["headers"]))
        hdr_cells = wt.rows[0].cells
        for i, h in enumerate(tbl["headers"]):
            hdr_cells[i].text = str(h)
        for row in tbl["rows"]:
            rc = wt.add_row().cells
            for i, val in enumerate(row):
                rc[i].text = str(val)

    d.save(filepath)


def generate_synthetic_legal_corpus(output_dir: str) -> Dict[str, str]:
    """Generates PDF and DOCX synthetic legal files on disk and returns their file paths."""
    os.makedirs(output_dir, exist_ok=True)
    sha_pdf = os.path.join(output_dir, "shareholders_agreement.pdf")
    sha_docx = os.path.join(output_dir, "shareholders_agreement.docx")
    msa_pdf = os.path.join(output_dir, "master_services_agreement.pdf")
    malformed_pdf = os.path.join(output_dir, "corrupted_side_letter.pdf")
    unocrd_pdf = os.path.join(output_dir, "partial_unocrd_scan.pdf")

    _render_pdf(sha_pdf, SHAREHOLDERS_AGREEMENT_BLOCKS, SHAREHOLDERS_TABLES, pagesize=LETTER)
    _render_docx(sha_docx, SHAREHOLDERS_AGREEMENT_BLOCKS, SHAREHOLDERS_TABLES)
    _render_pdf(msa_pdf, MSA_BLOCKS, MSA_TABLES, pagesize=A4)
    _render_pdf(malformed_pdf, MALFORMED_BLOCKS, [], pagesize=LETTER)
    _render_unocrd_scan_pdf(unocrd_pdf)

    return {
        "DOC_001_PDF": sha_pdf,
        "DOC_001_DOCX": sha_docx,
        "DOC_002_PDF": msa_pdf,
        "DOC_999_MALFORMED": malformed_pdf,
        "DOC_998_UNOCRD": unocrd_pdf,
    }
