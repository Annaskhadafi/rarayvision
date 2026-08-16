import logging
import re
import numpy as np
from typing import Optional, List, Dict, Any
import pdf_inspector

logger = logging.getLogger(__name__)

# Lazy singleton for RapidOCR
_rapid_ocr_instance = None

def get_rapid_ocr():
    global _rapid_ocr_instance
    if _rapid_ocr_instance is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _rapid_ocr_instance = RapidOCR()
            # Fast warm-up to pre-compile ONNX graph and eliminate first-request latency
            try:
                dummy_img = np.zeros((64, 64, 3), dtype=np.uint8)
                _rapid_ocr_instance(dummy_img)
            except Exception:
                pass
            logger.info("[PdfInspectorService] RapidOCR ONNX engine initialized and warmed up successfully.")
        except Exception as e:
            logger.error(f"[PdfInspectorService] Could not initialize RapidOCR: {e}")
            _rapid_ocr_instance = False
    return _rapid_ocr_instance


def format_ocr_to_markdown(ocr_result: list) -> str:
    """
    Reconstructs raw OCR bounding boxes and text tokens into clean, structured Markdown
    (Headings #/##, Lists, Tables, and Paragraphs) based on spatial geometry and line heights.
    Optimized for high-speed clustering with zero redundant allocations.
    """
    if not ocr_result:
        return ""

    parsed_items = []
    heights = []
    for item in ocr_result:
        if not item or len(item) < 2:
            continue
        box = item[0]
        text = str(item[1]).strip()
        score = float(item[2]) if len(item) > 2 else 1.0

        if not text:
            continue

        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        h = max(max_y - min_y, 1.0)
        w = max(max_x - min_x, 1.0)
        center_y = (min_y + max_y) * 0.5

        heights.append(h)
        parsed_items.append({
            "text": text,
            "min_x": min_x,
            "max_x": max_x,
            "min_y": min_y,
            "max_y": max_y,
            "center_y": center_y,
            "height": h,
            "width": w,
            "score": score
        })

    if not parsed_items:
        return ""

    # Sort all items from top to bottom
    parsed_items.sort(key=lambda it: it["center_y"])
    median_height = float(np.median(heights)) if heights else 14.0
    y_threshold = median_height * 0.6

    # Group items into horizontal lines with O(1) running average
    lines = []
    current_line = []
    current_line_y = None

    for item in parsed_items:
        if current_line_y is None:
            current_line = [item]
            current_line_y = item["center_y"]
        else:
            # If vertical distance is within threshold of line height, treat as same line
            if abs(item["center_y"] - current_line_y) < y_threshold:
                current_line.append(item)
                # O(1) update to running average center
                count = len(current_line)
                current_line_y = (current_line_y * (count - 1) + item["center_y"]) / count
            else:
                current_line.sort(key=lambda it: it["min_x"])
                lines.append(current_line)
                current_line = [item]
                current_line_y = item["center_y"]

    if current_line:
        current_line.sort(key=lambda it: it["min_x"])
        lines.append(current_line)

    # Format lines into Markdown
    md_output_lines = []
    
    for line in lines:
        if not line:
            continue

        line_texts = [it["text"] for it in line]
        line_height = sum(it["height"] for it in line) / len(line)
        line_str = " ".join(line_texts).strip()

        if not line_str:
            continue

        # Check if line looks like a table row (>= 2 columns with substantial spacing)
        is_table_row = False
        if len(line) >= 2:
            gaps = [line[i+1]["min_x"] - line[i]["max_x"] for i in range(len(line)-1)]
            if any(gap > median_height * 1.5 for gap in gaps):
                is_table_row = True

        if is_table_row:
            table_row = "| " + " | ".join(line_texts) + " |"
            md_output_lines.append(table_row)
            continue

        # Heading detection based on font height ratio
        if line_height >= median_height * 1.7:
            md_output_lines.append(f"\n# {line_str}\n")
        elif line_height >= median_height * 1.35:
            md_output_lines.append(f"\n## {line_str}\n")
        elif re.match(r'^([•\-\*]|\d+[\.\)])\s+', line_str):
            # List item
            clean_item = re.sub(r'^([•\-\*]|\d+[\.\)])\s*', '', line_str)
            md_output_lines.append(f"- {clean_item}")
        else:
            md_output_lines.append(line_str)

    # Clean up excess newlines
    md_text = "\n".join(md_output_lines)
    md_text = re.sub(r'\n{3,}', '\n\n', md_text).strip()
    return md_text


class PdfInspectorService:
    @staticmethod
    def process_pdf(file_bytes: bytes, pages: Optional[List[int]] = None, auto_ocr: bool = True) -> Dict[str, Any]:
        """
        Full PDF processing with Hybrid OCR auto-fallback:
        1. Fast inspector analyzes PDF type, confidence, and pages needing OCR.
        2. If auto_ocr is True and scanned pages are detected, automatically runs RapidOCR
           on those specific pages and reconstructs clean Markdown.
        """
        try:
            result = pdf_inspector.process_pdf_bytes(file_bytes, pages=pages)
            
            pdf_type = str(getattr(result, 'pdf_type', 'unknown'))
            confidence = float(getattr(result, 'confidence', 0.0))
            page_count = int(getattr(result, 'page_count', 0))
            pages_needing_ocr = list(getattr(result, 'pages_needing_ocr', []))
            base_markdown = getattr(result, 'markdown', "") or ""

            ocr_applied_pages = []
            final_markdown = base_markdown

            # Only run Hybrid OCR if the document is genuinely an image/scan (almost zero extracted text)
            has_digital_text = len(base_markdown.strip()) > 300
            needs_ocr = (not has_digital_text) and (bool(pages_needing_ocr) or pdf_type in ["scanned", "image_based"])

            if auto_ocr and needs_ocr:
                try:
                    import pypdfium2 as pdfium
                    ocr_engine = get_rapid_ocr()

                    if ocr_engine:
                        pdf_doc = pdfium.PdfDocument(file_bytes)
                        total_doc_pages = len(pdf_doc)
                        
                        target_pages = pages_needing_ocr if pages_needing_ocr else list(range(1, total_doc_pages + 1))
                        if pages:
                            target_pages = [p for p in target_pages if p in pages]
                        # Cap OCR to max 15 pages to prevent RAM exhaustion on large files
                        target_pages = target_pages[:15]

                        # Extract per-page markdown from pdf-inspector for native text pages
                        pages_result = pdf_inspector.extract_pages_markdown_bytes(file_bytes, pages=pages)
                        native_pages_dict = {}
                        if hasattr(pages_result, 'pages'):
                            for p in pages_result.pages:
                                native_pages_dict[int(getattr(p, 'page', 0))] = getattr(p, 'markdown', "")

                        combined_pages = []
                        for page_idx in range(min(total_doc_pages, 30)):
                            page_num = page_idx + 1
                            if pages and page_num not in pages:
                                continue

                            if page_num in target_pages:
                                page = pdf_doc[page_idx]
                                # Zero-copy rendering direct to numpy array (1.5x scale)
                                bitmap = page.render(scale=1.5)
                                img_np = bitmap.to_numpy()

                                ocr_res, _ = ocr_engine(img_np)
                                page_md = format_ocr_to_markdown(ocr_res)

                                if page_md:
                                    ocr_applied_pages.append(page_num)
                                    combined_pages.append(f"<!-- Page {page_num} (OCR Scanned) -->\n\n{page_md}")
                                else:
                                    native_md = native_pages_dict.get(page_num, "")
                                    combined_pages.append(f"<!-- Page {page_num} -->\n\n{native_md}" if native_md else "")
                            else:
                                native_md = native_pages_dict.get(page_num, "")
                                combined_pages.append(f"<!-- Page {page_num} (Native Text) -->\n\n{native_md}")

                        final_markdown = "\n\n---\n\n".join([p for p in combined_pages if p.strip()]).strip()
                except Exception as ocr_err:
                    logger.warning(f"[PdfInspectorService] Hybrid OCR fallback encountered an issue: {ocr_err}")

            ocr_reasons = {}
            if hasattr(result, 'ocr_reasons_by_page') and result.ocr_reasons_by_page:
                try:
                    ocr_reasons = dict(result.ocr_reasons_by_page)
                except Exception:
                    ocr_reasons = str(result.ocr_reasons_by_page)

            return {
                "pdf_type": pdf_type,
                "confidence": confidence,
                "page_count": page_count,
                "title": getattr(result, 'title', None),
                "markdown": final_markdown,
                "has_encoding_issues": bool(getattr(result, 'has_encoding_issues', False)),
                "is_complex_layout": bool(getattr(result, 'is_complex_layout', False)),
                "pages_needing_ocr": pages_needing_ocr,
                "ocr_applied_pages": ocr_applied_pages,
                "pages_with_columns": list(getattr(result, 'pages_with_columns', [])),
                "pages_with_tables": list(getattr(result, 'pages_with_tables', [])),
                "ocr_reasons_by_page": ocr_reasons,
                "processing_time_ms": float(getattr(result, 'processing_time_ms', 0.0))
            }
        except Exception as e:
            logger.error(f"[PdfInspectorService] Error in process_pdf: {e}", exc_info=True)
            raise ValueError(f"Failed to process PDF: {str(e)}")

    @staticmethod
    def ocr_scanned_pdf(file_bytes: bytes, pages: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        Directly performs OCR on PDF pages and converts bounding boxes into structured Markdown.
        """
        try:
            import pypdfium2 as pdfium
            ocr_engine = get_rapid_ocr()
            if not ocr_engine:
                raise ValueError("RapidOCR ONNX engine is not available.")

            pdf_doc = pdfium.PdfDocument(file_bytes)
            total_doc_pages = len(pdf_doc)
            
            pages_output = []
            all_md = []

            for page_idx in range(total_doc_pages):
                page_num = page_idx + 1
                if pages and page_num not in pages:
                    continue

                page = pdf_doc[page_idx]
                bitmap = page.render(scale=2.0)
                img_np = bitmap.to_numpy()

                ocr_res, _ = ocr_engine(img_np)
                page_md = format_ocr_to_markdown(ocr_res)
                
                pages_output.append({
                    "page": page_num,
                    "markdown": page_md,
                    "token_count": len(ocr_res) if ocr_res else 0
                })
                all_md.append(f"<!-- Page {page_num} (OCR Scanned) -->\n\n{page_md}")

            return {
                "total_pages": total_doc_pages,
                "processed_pages": len(pages_output),
                "markdown": "\n\n---\n\n".join(all_md),
                "pages": pages_output
            }
        except Exception as e:
            logger.error(f"[PdfInspectorService] Error in ocr_scanned_pdf: {e}", exc_info=True)
            raise ValueError(f"Failed to OCR scanned PDF: {str(e)}")

    @staticmethod
    def classify_pdf(file_bytes: bytes) -> Dict[str, Any]:
        """
        Fast PDF classification without extracting full text.
        Determines whether document is text_based, scanned, image_based, or mixed.
        """
        try:
            res = pdf_inspector.classify_pdf_bytes(file_bytes)
            
            ocr_reasons = {}
            if hasattr(res, 'ocr_reasons_by_page') and res.ocr_reasons_by_page:
                try:
                    ocr_reasons = dict(res.ocr_reasons_by_page)
                except Exception:
                    ocr_reasons = str(res.ocr_reasons_by_page)

            return {
                "pdf_type": str(getattr(res, 'pdf_type', 'unknown')),
                "confidence": float(getattr(res, 'confidence', 0.0)),
                "page_count": int(getattr(res, 'page_count', 0)),
                "pages_needing_ocr": list(getattr(res, 'pages_needing_ocr', [])),
                "has_encoding_issues": bool(getattr(res, 'has_encoding_issues', False)),
                "ocr_reasons_by_page": ocr_reasons
            }
        except Exception as e:
            logger.error(f"[PdfInspectorService] Error in classify_pdf: {e}", exc_info=True)
            raise ValueError(f"Failed to classify PDF: {str(e)}")

    @staticmethod
    def extract_text(file_bytes: bytes) -> Dict[str, Any]:
        """
        Extract raw plain text from PDF stream.
        """
        try:
            text = pdf_inspector.extract_text_bytes(file_bytes)
            return {
                "text": text,
                "length": len(text)
            }
        except Exception as e:
            logger.error(f"[PdfInspectorService] Error in extract_text: {e}", exc_info=True)
            raise ValueError(f"Failed to extract text from PDF: {str(e)}")

    @staticmethod
    def extract_markdown(file_bytes: bytes, pages: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        Extract per-page Markdown strings and layout metadata.
        """
        try:
            result = pdf_inspector.extract_pages_markdown_bytes(file_bytes, pages=pages)
            pages_list = []
            if hasattr(result, 'pages'):
                for p in result.pages:
                    pages_list.append({
                        "page": int(getattr(p, 'page', 0)),
                        "markdown": getattr(p, 'markdown', ""),
                        "needs_ocr": bool(getattr(p, 'needs_ocr', False)),
                        "ocr_reasons": list(getattr(p, 'ocr_reasons', [])) if hasattr(p, 'ocr_reasons') else []
                    })
            return {
                "total_pages": int(getattr(result, 'total_pages', len(pages_list))),
                "pages": pages_list
            }
        except Exception as e:
            logger.error(f"[PdfInspectorService] Error in extract_markdown: {e}", exc_info=True)
            raise ValueError(f"Failed to extract markdown pages: {str(e)}")

    @staticmethod
    def extract_positions(file_bytes: bytes) -> Dict[str, Any]:
        """
        Position-aware text extraction returning coordinates, bounding boxes, font info, and formatting.
        """
        try:
            items = pdf_inspector.extract_text_with_positions_bytes(file_bytes)
            text_items = []
            for item in items:
                text_items.append({
                    "text": getattr(item, 'text', ''),
                    "page": int(getattr(item, 'page', 1)),
                    "x": float(getattr(item, 'x', 0.0)),
                    "y": float(getattr(item, 'y', 0.0)),
                    "width": float(getattr(item, 'width', 0.0)),
                    "height": float(getattr(item, 'height', 0.0)),
                    "font": getattr(item, 'font', ''),
                    "font_size": float(getattr(item, 'font_size', 0.0)),
                    "is_bold": bool(getattr(item, 'is_bold', False)),
                    "is_italic": bool(getattr(item, 'is_italic', False)),
                    "is_underline": bool(getattr(item, 'is_underline', False)),
                    "is_strikeout": bool(getattr(item, 'is_strikeout', False)),
                    "item_type": str(getattr(item, 'item_type', '')),
                    "mcid": getattr(item, 'mcid', None)
                })
            return {
                "count": len(text_items),
                "items": text_items
            }
        except Exception as e:
            logger.error(f"[PdfInspectorService] Error in extract_positions: {e}", exc_info=True)
            raise ValueError(f"Failed to extract positioned text items: {str(e)}")

    @staticmethod
    def extract_structure(file_bytes: bytes) -> Dict[str, Any]:
        """
        Extract structure elements from tagged PDFs.
        """
        try:
            elements = pdf_inspector.extract_structure_elements_bytes(file_bytes)
            elem_list = []
            for e in elements:
                elem_list.append({
                    "page": int(getattr(e, 'page', 1)),
                    "mcid": getattr(e, 'mcid', None),
                    "role": getattr(e, 'role', ''),
                    "title": getattr(e, 'title', None),
                    "lang": getattr(e, 'lang', None),
                    "alt": getattr(e, 'alt', None),
                    "actual_text": getattr(e, 'actual_text', None)
                })
            return {
                "count": len(elem_list),
                "elements": elem_list
            }
        except Exception as e:
            logger.error(f"[PdfInspectorService] Error in extract_structure: {e}", exc_info=True)
            raise ValueError(f"Failed to extract structure elements: {str(e)}")
