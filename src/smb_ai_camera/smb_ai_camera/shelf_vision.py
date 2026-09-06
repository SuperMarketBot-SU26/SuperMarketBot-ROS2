import os
import time
import cv2
import numpy as np
import unicodedata
from PIL import Image, ImageDraw, ImageFont
from typing import Dict, List, Any, Tuple, Optional
from ultralytics import YOLO
from product_matcher import ProductFeatureMatcher

def remove_accents(s: str) -> str:
    if not isinstance(s, str):
        return s
    s = s.replace('Đ', 'D').replace('đ', 'd')
    return unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')

class ShelfVisionEngine:
    """
    YOLO-based Supermarket Shelf Density and Shelf Classification Engine.
    Supports multi-tier shelf analytics (Tầng 1 - Dưới, Tầng 2 - Trên).
    """
    def __init__(self, model_path: str = "best.pt", conf_threshold: float = 0.15, resource_dir: Optional[str] = None):
        import os
        if resource_dir and not os.path.isabs(model_path):
            model_path = os.path.join(resource_dir, "models", model_path)
            
        if not os.path.exists(model_path):
            if os.path.exists("runs/detect/train/weights/best.pt"):
                model_path = "runs/detect/train/weights/best.pt"
            elif os.path.exists("weights/best.pt"):
                model_path = "weights/best.pt"
            else:
                model_path = "yolov8n.pt"

        self.conf_threshold = conf_threshold
        self.smooth_split_y: Optional[float] = None
        print(f"[ShelfVision] Loading YOLO model: {model_path}...")
        self.model = YOLO(model_path)
        print(f"[ShelfVision] YOLO Model ({model_path}) initialized successfully with classes: {len(self.model.names)}")

        # Initialize 2-Stage Product Feature Matcher (MobileNetV3)
        if resource_dir:
            ref_prod_dir = os.path.join(resource_dir, "reference_products")
        else:
            ref_prod_dir = os.path.join(os.path.dirname(__file__), "reference_products")
        self.matcher = ProductFeatureMatcher(base_dir=ref_prod_dir)

        # Preload TrueType fonts for crisp Vietnamese rendering (Fallback to default if not found)
        try:
            # Try to use a common Linux font instead of Windows fonts
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            self.font_main = ImageFont.truetype(font_path, 15)
            self.font_bold = ImageFont.truetype(font_path, 16)
            self.font_small = ImageFont.truetype(font_path, 12)
        except Exception:
            self.font_main = ImageFont.load_default()
            self.font_bold = ImageFont.load_default()
            self.font_small = ImageFont.load_default()

        # Initialize ArUco Detector (DICT_4X4_50)
        try:
            self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
            self.aruco_params = cv2.aruco.DetectorParameters()
            self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)
        except Exception:
            self.aruco_dict = cv2.aruco.Dictionary_get(cv2.aruco.DICT_4X4_50)
            self.aruco_params = cv2.aruco.DetectorParameters_create()
            self.aruco_detector = None

        # Mapping COCO & Supermarket detected objects to Shelf Categories
        self.CLASS_TO_SHELF_MAP = {
            # Kệ 1: Đồ Ăn Vặt (ShelfID = 1)
            "chocopie": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "banh_tet": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "banh_chung": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "dau_phong": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "snack_lays": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "oishi_snack": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "pinattsu": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "snack_mix": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "banh_mi_que": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "snack_muc": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "snack_bap": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "sandwich": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "donut": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "cake": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "cookie": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),
            "bag": (1, "Kệ 1 - Đồ Ăn Vặt", "Snack & Đồ Ăn Vặt"),

            # Kệ 2: Nước Giải Khát & Đồ Uống (ShelfID = 2)
            "coca_cola": (2, "Kệ 2 - Nước Giải Khát & Đồ Uống", "Nước Giải Khát"),
            "sting": (2, "Kệ 2 - Nước Giải Khát & Đồ Uống", "Nước Giải Khát"),
            "binh_nuoc": (2, "Kệ 2 - Nước Giải Khát & Đồ Uống", "Nước Giải Khát"),
            "mirinda": (2, "Kệ 2 - Nước Giải Khát & Đồ Uống", "Nước Giải Khát"),
            "pepsi": (2, "Kệ 2 - Nước Giải Khát & Đồ Uống", "Nước Giải Khát"),
            "red_bull": (2, "Kệ 2 - Nước Giải Khát & Đồ Uống", "Nước Giải Khát"),
            "nuoc_khoang_lavie": (2, "Kệ 2 - Nước Giải Khát & Đồ Uống", "Nước Giải Khát"),
            "chai_nhua": (2, "Kệ 2 - Nước Giải Khát & Đồ Uống", "Nước Giải Khát"),
            "heineken": (2, "Kệ 2 - Nước Giải Khát & Đồ Uống", "Nước Giải Khát"),
            "bottle": (2, "Kệ 2 - Nước Giải Khát & Đồ Uống", "Nước Giải Khát"),
            "wine glass": (2, "Kệ 2 - Nước Giải Khát & Đồ Uống", "Nước Giải Khát"),
            "can": (2, "Kệ 2 - Nước Giải Khát & Đồ Uống", "Nước Giải Khát"),

            # Kệ 3: Thực Phẩm Tươi Sống (ShelfID = 3)
            "thit_bo": (3, "Kệ 3 - Thực Phẩm Tươi Sống", "Thực Phẩm Tươi"),
            "thit_heo": (3, "Kệ 3 - Thực Phẩm Tươi Sống", "Thực Phẩm Tươi"),
            "ca_chep": (3, "Kệ 3 - Thực Phẩm Tươi Sống", "Thực Phẩm Tươi"),
            "rau_muong": (3, "Kệ 3 - Thực Phẩm Tươi Sống", "Thực Phẩm Tươi"),
            "banana": (3, "Kệ 3 - Thực Phẩm Tươi Sống", "Thực Phẩm Tươi"),
            "apple": (3, "Kệ 3 - Thực Phẩm Tươi Sống", "Thực Phẩm Tươi"),
            "orange": (3, "Kệ 3 - Thực Phẩm Tươi Sống", "Thực Phẩm Tươi"),
            "broccoli": (3, "Kệ 3 - Thực Phẩm Tươi Sống", "Thực Phẩm Tươi"),
            "carrot": (3, "Kệ 3 - Thực Phẩm Tươi Sống", "Thực Phẩm Tươi"),
            "hot dog": (3, "Kệ 3 - Thực Phẩm Tươi Sống", "Thực Phẩm Tươi"),
            "pizza": (3, "Kệ 3 - Thực Phẩm Tươi Sống", "Thực Phẩm Tươi"),

            # Kệ 4: Mì Ăn Liền & Đóng Gói (ShelfID = 4)
            "ly_mi_life_cup": (4, "Kệ 4 - Mì Ăn Liền & Đóng Gói", "Mì Ăn Liền"),
            "mi_indomie": (4, "Kệ 4 - Mì Ăn Liền & Đóng Gói", "Mì Ăn Liền"),
            "mi_3_mien": (4, "Kệ 4 - Mì Ăn Liền & Đóng Gói", "Mì Ăn Liền"),
            "mi_a_one": (4, "Kệ 4 - Mì Ăn Liền & Đóng Gói", "Mì Ăn Liền"),
            "chao_an_lien": (4, "Kệ 4 - Mì Ăn Liền & Đóng Gói", "Cháo Ăn Liền"),
            "bowl": (4, "Kệ 4 - Mì Ăn Liền & Đóng Gói", "Mì Ăn Liền"),
            
            # Kệ 5: Đồ Gia Dụng & Tiện Ích (ShelfID = 5)
            "khan_uot_gau": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "khan_uot_bumbo": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "to_an_com": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "tho_giu_nhiet": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "ong_tam": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "tam_tre": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "tui_giay": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "cup": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "fork": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "knife": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "spoon": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "scissors": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "toothbrush": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "box": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "mang_boc_thuc_pham": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),
            "food_wrap": (5, "Kệ 5 - Đồ Gia Dụng & Tiện Ích", "Đồ Gia Dụng"),

            # Kệ 6: Gia Vị & Trà (ShelfID = 6)
            "hu_gia_vi_vang": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
            "hu_gia_vi_do": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
            "nuoc_tuong_chinsu": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
            "nuoc_tuong_maggi": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
            "sa_te_cay": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
            "muoi_ot_chanh": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
            "dau_me_meizan": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
            "hu_muoi_ot_tay_ninh": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
            "tieu_den_phu_quoc": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
            "tra_ngoc_an": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
            "tra_thien_thao": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
            "vase": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
            "potted plant": (6, "Kệ 6 - Gia Vị & Trà", "Gia Vị & Trà"),
        }

        # Color palette for modern bounding boxes (BGR)
        self.SHELF_COLORS = {
            1: (255, 140, 0),   # Orange (Kệ 1 Snack)
            2: (0, 200, 255),   # Cyan/Yellow (Kệ 2 Drinks)
            3: (0, 220, 100),   # Green (Kệ 3 Fresh food)
            4: (0, 100, 255),   # Red/Orange (Kệ 4 Noodles)
            5: (220, 100, 255), # Purple (Kệ 5 Houseware)
            6: (180, 220, 0),   # Olive Green (Kệ 6 Spices)
            0: (128, 128, 128)  # Gray (Unknown)
        }

    def analyze_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Runs YOLO detection on the input frame and computes density % and shelf classification.
        """
        start_time = time.time()
        h, w = frame.shape[:2]
        total_frame_area = float(h * w)

        # 1. Detect ArUco Markers for 100% Deterministic Shelf Identification
        detected_tag_id = None
        aruco_boxes = []
        try:
            if self.aruco_detector is not None:
                corners, ids, _ = self.aruco_detector.detectMarkers(frame)
            else:
                corners, ids, _ = cv2.aruco.detectMarkers(frame, self.aruco_dict, parameters=self.aruco_params)

            if ids is not None and len(ids) > 0:
                for i, tag_id_val in enumerate(ids.flatten()):
                    tid = int(tag_id_val)
                    if 1 <= tid <= 6:
                        detected_tag_id = tid
                        c = corners[i][0]
                        x_min, y_min = int(np.min(c[:, 0])), int(np.min(c[:, 1]))
                        x_max, y_max = int(np.max(c[:, 0])), int(np.max(c[:, 1]))
                        aruco_boxes.append({"tagId": tid, "box": [x_min, y_min, x_max, y_max]})
        except Exception as e:
            print(f"[ShelfVision] ArUco detection warning: {e}")

        # Run inference (YOLO automatically optimizes resizing)
        results = self.model(frame, conf=self.conf_threshold, verbose=False)[0]

        detected_objects = []
        shelf_votes: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
        total_product_area = 0.0
        total_empty_area = 0.0

        for box in results.boxes:
            cls_id = int(box.cls[0].item())
            class_name = self.model.names.get(cls_id, f"obj_{cls_id}")
            conf = float(box.conf[0].item())
            xyxy = box.xyxy[0].tolist()
            x1, y1, x2, y2 = map(int, xyxy)

            # Clamp coordinates
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            bw, bh = max(0, x2 - x1), max(0, y2 - y1)
            box_area = float(bw * bh)

            is_empty = (class_name == "empty_slot" or class_name == "empty")

            if is_empty:
                total_empty_area += box_area
            else:
                total_product_area += box_area

            detected_objects.append({
                "label": class_name,
                "confidence": round(round(conf * 20) / 20.0, 2),
                "box": [x1, y1, x2, y2],
                "shelfId": detected_tag_id or 0,
                "isEmptySlot": is_empty
            })

        # Filter out stray background objects clearly outside the shelf boundaries if ArUco tag is detected
        if aruco_boxes:
            tag_b = aruco_boxes[0]["box"]
            tag_w = tag_b[2] - tag_b[0]
            shelf_x_min = max(0, tag_b[0] - 25)
            shelf_x_max = min(w, tag_b[0] + int(tag_w * 8.8))

            detected_objects = [
                o for o in detected_objects
                if (o["box"][2] >= shelf_x_min and o["box"][0] <= shelf_x_max)
            ]

        # --- Merge fragmented product proposals (e.g. fish body + tail, duplicate proposals) ---
        raw_products = [o for o in detected_objects if not o["isEmptySlot"]]
        raw_products = self._merge_overlapping_products(raw_products)
        raw_empties  = [o for o in detected_objects if o["isEmptySlot"]]


        def _is_empty_suppressed(empty_box: List[int], products: List[Dict]) -> bool:
            """
            Suppress empty_slot box if it is almost entirely covered by products:
            - ANY single product covers > 60% of the empty box, OR
            - COMBINED product coverage > 70% of empty box area.
            (Nới lỏng ngưỡng vì model v2 đã phân tách box khá tốt, tránh xóa nhầm khoảng trống nhỏ)
            """
            empty_area = float(
                (empty_box[2] - empty_box[0]) * (empty_box[3] - empty_box[1])
            )
            if empty_area <= 0:
                return True

            total_covered = 0.0
            for prod in products:
                ix1 = max(empty_box[0], prod["box"][0])
                iy1 = max(empty_box[1], prod["box"][1])
                ix2 = min(empty_box[2], prod["box"][2])
                iy2 = min(empty_box[3], prod["box"][3])
                if ix2 > ix1 and iy2 > iy1:
                    inter = float((ix2 - ix1) * (iy2 - iy1))
                    # Single product covers > 60% of empty box → suppress
                    if inter / empty_area > 0.60:
                        return True
                    total_covered += inter

            # Combined all products cover > 70% of empty box → suppress
            return (total_covered / empty_area) > 0.70

        filtered_empties = [
            e for e in raw_empties
            if not _is_empty_suppressed(e["box"], raw_products)
        ]

        # Recalculate total areas after filtering
        total_product_area = sum(
            float((o["box"][2]-o["box"][0]) * (o["box"][3]-o["box"][1]))
            for o in raw_products
        )
        total_empty_area = sum(
            float((o["box"][2]-o["box"][0]) * (o["box"][3]-o["box"][1]))
            for o in filtered_empties
        )

        # Stage 2: Feature Matching - Identify specific product names using MobileNetV3
        decomposed_products = []
        for prod in raw_products:
            bx1, by1, bx2, by2 = prod["box"]
            crop = frame[by1:by2, bx1:bx2]
            ch = crop.shape[0]

            is_stack = False
            # Check if this box contains vertically stacked distinct products (e.g. 2 bags of tea)
            if ch >= 70:
                top_crop = crop[:int(ch * 0.52), :]
                bot_crop = crop[int(ch * 0.48):, :]
                m_top = self.matcher.match_crop(top_crop, shelf_id=detected_tag_id)
                m_bot = self.matcher.match_crop(bot_crop, shelf_id=detected_tag_id)

                s_top = self.CLASS_TO_SHELF_MAP.get(m_top["productId"], (0,))[0]
                s_bot = self.CLASS_TO_SHELF_MAP.get(m_bot["productId"], (0,))[0]

                if (m_top["isMatched"] and m_bot["isMatched"] and 
                    m_top["productId"] != m_bot["productId"] and
                    s_top == s_bot and s_top > 0 and
                    m_top["similarity"] >= 0.82 and m_bot["similarity"] >= 0.82):
                    is_stack = True
                    mid_y = by1 + ch // 2

                    p_top = dict(prod)
                    p_top["box"] = [bx1, by1, bx2, mid_y]
                    p_top["label"] = m_top["productName"]
                    p_top["productId"] = m_top["productId"]
                    p_top["similarity"] = round(round(m_top["similarity"] * 20) / 20.0, 2)
                    p_top["isMatched"] = True

                    p_bot = dict(prod)
                    p_bot["box"] = [bx1, mid_y, bx2, by2]
                    p_bot["label"] = m_bot["productName"]
                    p_bot["productId"] = m_bot["productId"]
                    p_bot["similarity"] = round(round(m_bot["similarity"] * 20) / 20.0, 2)
                    p_bot["isMatched"] = True

                    decomposed_products.extend([p_top, p_bot])

            if not is_stack:
                match_res = self.matcher.match_crop(crop, shelf_id=detected_tag_id)
                prod["label"] = match_res["productName"]
                prod["productId"] = match_res["productId"]
                prod["similarity"] = round(round(match_res["similarity"] * 20) / 20.0, 2)
                prod["isMatched"] = match_res["isMatched"]
                decomposed_products.append(prod)

        raw_products = decomposed_products

        inventory_counts: Dict[str, int] = {}
        for prod in raw_products:
            pname = prod["label"]
            inventory_counts[pname] = inventory_counts.get(pname, 0) + 1

        # Rebuild final detected_objects list with filtered empties
        detected_objects = raw_products + filtered_empties

        # Multi-Tier Shelf Segmentation (Tầng 1 - Dưới, Tầng 2 - Trên)
        detected_objects, split_y, tier_summary = self._compute_tiers(detected_objects, h)

        # Calculate Density using Universal Product & Empty Slot Detection
        product_objects = raw_products
        yolo_empty_objects = filtered_empties
        num_products = len(product_objects)
        num_empty = len(yolo_empty_objects)

        # Color-based empty shelf detection as auxiliary indicator
        shelf_color_ratio = self._detect_shelf_color_ratio(frame, product_objects)

        # Compute Density Percentage
        if num_products == 0 and num_empty == 0:
            density_pct = 0.0
            stock_status = "Out of Stock"
        elif num_products == 0:
            density_pct = 0.0
            stock_status = "Out of Stock"
        elif num_empty > 0:
            # Direct ratio between product area and total detected shelf space
            total_active_area = total_product_area + total_empty_area
            raw_ratio = (total_product_area / total_active_area) * 100.0 if total_active_area > 0 else 50.0
            density_pct = round(max(5.0, min(95.0, raw_ratio)), 1)
            
            if density_pct >= 70.0 and num_empty <= 1:
                stock_status = "Well Stocked"
            elif density_pct >= 35.0:
                stock_status = "Normal"
            else:
                stock_status = "Low Stock"
        else:
            # No empty slots detected by YOLO -> use product count and frame coverage
            coverage_ratio = min(1.0, (total_product_area / (total_frame_area * 0.65)))
            raw_pct = round(coverage_ratio * 100.0, 1)
            if num_products >= 3 and shelf_color_ratio < 0.20:
                density_pct = max(80.0, min(95.0, 60.0 + num_products * 8.0))
                stock_status = "Well Stocked"
            elif num_products >= 1:
                density_pct = max(45.0, min(75.0, raw_pct))
                stock_status = "Normal"
            else:
                density_pct = 0.0
                stock_status = "Out of Stock"

        empty_percentage = round(max(0.0, 100.0 - density_pct), 1)

        # Determine Shelf Category:
        # Check product votes across shelves
        for prod in raw_products:
            pid = prod.get("productId")
            if pid in self.CLASS_TO_SHELF_MAP:
                s_id, _, _ = self.CLASS_TO_SHELF_MAP[pid]
                shelf_votes[s_id] = shelf_votes.get(s_id, 0) + 1

        top_voted_shelf = max(shelf_votes, key=shelf_votes.get) if shelf_votes else 0
        top_votes = shelf_votes.get(top_voted_shelf, 0)

        # PRIORITY 1: ArUco Tag (Deterministic Shelf Identification)
        # PRIORITY 2: Fallback to majority product vote
        SHELF_NAMES = {
            1: "Kệ 1 - Đồ Ăn Vặt",
            2: "Kệ 2 - Nước Giải Khát & Đồ Uống",
            3: "Kệ 3 - Thực Phẩm Tươi Sống",
            4: "Kệ 4 - Mì Ăn Liền & Đóng Gói",
            5: "Kệ 5 - Đồ Gia Dụng & Tiện Ích",
            6: "Kệ 6 - Gia Vị & Trà"
        }

        if detected_tag_id is not None:
            # If tag matches products or products have no overwhelming mismatch, trust tag
            if top_votes >= 2 and top_voted_shelf != detected_tag_id and shelf_votes.get(detected_tag_id, 0) == 0:
                dominant_shelf_id = top_voted_shelf
                shelf_category = f"[KỆ {top_voted_shelf}] {SHELF_NAMES.get(top_voted_shelf)} (Tag #{detected_tag_id})"
                tag_locked = True
            else:
                dominant_shelf_id = detected_tag_id
                shelf_category = f"[TAG #{detected_tag_id}] {SHELF_NAMES.get(detected_tag_id)}"
                tag_locked = True
        elif top_votes >= 3:
            dominant_shelf_id = top_voted_shelf
            shelf_category = f"{SHELF_NAMES.get(top_voted_shelf)} (Dự đoán theo SP)"
            tag_locked = False
        else:
            dominant_shelf_id = 0
            shelf_category = "Kệ Hàng Siêu Thị (Đang quét)"
            tag_locked = False

        inference_time_ms = round((time.time() - start_time) * 1000, 1)

        return {
            "shelfId": dominant_shelf_id,
            "shelfCategory": shelf_category,
            "tagDetected": tag_locked,
            "arucoTagId": detected_tag_id,
            "arucoBoxes": aruco_boxes,
            "densityPct": density_pct,
            "densityPercentage": density_pct,
            "emptyPercentage": empty_percentage,
            "stockStatus": stock_status,
            "isOutOfStock": (stock_status == "Out of Stock"),
            "isLowStock": (stock_status == "Low Stock"),
            "totalObjects": num_products,
            "totalEmptySlots": num_empty,
            "shelfColorRatio": round(shelf_color_ratio * 100, 1),
            "inferenceTimeMs": inference_time_ms,
            "detectedObjects": detected_objects,
            "detectedProducts": [
                {
                    "productId": o.get("productId"),
                    "productName": o.get("label"),
                    "similarity": o.get("similarity"),
                    "confidence": o.get("confidence"),
                    "tier": o.get("tier"),
                    "tierName": o.get("tierName"),
                    "box": o.get("box")
                }
                for o in raw_products
            ],
            "inventoryCounts": inventory_counts,
            "shelfVotes": shelf_votes,
            "splitY": tier_summary.get("splitY"),
            "isMultiTier": tier_summary.get("isMultiTier", False),
            "tierSummary": tier_summary,
            "tier1": tier_summary.get("tier1"),
            "tier2": tier_summary.get("tier2")
        }

    def _merge_overlapping_products(self, prods: List[Dict]) -> List[Dict]:
        """
        Merges fragmented or heavily overlapping bounding boxes belonging to the same product item
        (e.g., body + tail of hand-drawn fish, multiple box proposals on same meat cutout).
        """
        if len(prods) <= 1:
            return prods

        # Filter out tiny noise slivers (< 35px width or height)
        prods = [p for p in prods if (p["box"][2] - p["box"][0]) >= 35 and (p["box"][3] - p["box"][1]) >= 35]

        sorted_prods = sorted(prods, key=lambda x: x.get("confidence", 0.0), reverse=True)
        merged = []
        used = [False] * len(sorted_prods)

        for i in range(len(sorted_prods)):
            if used[i]:
                continue
            p1 = dict(sorted_prods[i])
            b1 = list(p1["box"])
            used[i] = True

            for j in range(i + 1, len(sorted_prods)):
                if used[j]:
                    continue
                p2 = sorted_prods[j]
                b2 = p2["box"]

                ix1 = max(b1[0], b2[0])
                iy1 = max(b1[1], b2[1])
                ix2 = min(b1[2], b2[2])
                iy2 = min(b1[3], b2[3])

                should_merge = False
                if ix2 > ix1 and iy2 > iy1:
                    inter_area = float((ix2 - ix1) * (iy2 - iy1))
                    area1 = float((b1[2] - b1[0]) * (b1[3] - b1[1]))
                    area2 = float((b2[2] - b2[0]) * (b2[3] - b2[1]))
                    min_area = min(area1, area2)

                    # If intersection covers > 8% of smaller box, merge into bounding container
                    if min_area > 0 and (inter_area / min_area) > 0.08:
                        should_merge = True
                else:
                    # Check vertically aligned fragments of tall items (bottle neck + body)
                    x_overlap = max(0, min(b1[2], b2[2]) - max(b1[0], b2[0]))
                    min_w = min(b1[2] - b1[0], b2[2] - b2[0])
                    y_gap = max(0, max(b1[1], b2[1]) - min(b1[3], b2[3]))
                    if min_w > 0 and (x_overlap / min_w) > 0.60 and y_gap < 20:
                        should_merge = True

                if should_merge:
                    b1[0] = min(b1[0], b2[0])
                    b1[1] = min(b1[1], b2[1])
                    b1[2] = max(b1[2], b2[2])
                    b1[3] = max(b1[3], b2[3])
                    p1["box"] = b1
                    p1["confidence"] = max(p1.get("confidence", 0.0), p2.get("confidence", 0.0))
                    used[j] = True

            merged.append(p1)
        return merged

    def _compute_tiers(self, detected_objects: List[Dict], frame_h: int) -> Tuple[List[Dict], Optional[float], Dict[str, Any]]:
        """
        Clusters detected objects into horizontal tiers (Tầng 1 - Dưới, Tầng 2 - Trên).
        Computes per-tier statistics: density percentage, product count, empty count, and stock status.
        """
        if not detected_objects:
            empty_t = {
                "densityPct": 0.0, "emptyPercentage": 100.0, "stockStatus": "Empty",
                "productCount": 0, "emptyCount": 0, "totalObjects": 0
            }
            return detected_objects, None, {
                "tierCount": 0, "isMultiTier": False, "splitY": None,
                "tier1": {**empty_t, "tierId": 1, "tierName": "Tầng 1 (Dưới)"},
                "tier2": {**empty_t, "tierId": 2, "tierName": "Tầng 2 (Trên)"}
            }

        # Compute Center Y of all detected objects
        all_cy = [(obj["box"][1] + obj["box"][3]) / 2.0 for obj in detected_objects]
        min_cy, max_cy = min(all_cy), max(all_cy)

        # Check if objects vertically span across multiple levels (at least 16% frame height)
        is_multi_tier = (max_cy - min_cy) >= (frame_h * 0.16) and len(detected_objects) >= 2

        if is_multi_tier:
            # 1D 2-means clustering
            c_top = min_cy
            c_bottom = max_cy
            for _ in range(6):
                g_top = [y for y in all_cy if abs(y - c_top) <= abs(y - c_bottom)]
                g_bottom = [y for y in all_cy if abs(y - c_top) > abs(y - c_bottom)]
                if g_top:
                    c_top = sum(g_top) / len(g_top)
                if g_bottom:
                    c_bottom = sum(g_bottom) / len(g_bottom)

            current_split = (c_top + c_bottom) / 2.0
            if self.smooth_split_y is None:
                self.smooth_split_y = current_split
            else:
                self.smooth_split_y = 0.8 * self.smooth_split_y + 0.2 * current_split
            split_y = self.smooth_split_y
        else:
            split_y = self.smooth_split_y if self.smooth_split_y is not None else (frame_h * 0.5)

        # Assign tier to each object:
        # Tier 2: Tầng Trên (Upper level)
        # Tier 1: Tầng Dưới (Lower level)
        for obj in detected_objects:
            cy = (obj["box"][1] + obj["box"][3]) / 2.0
            obj["tier"] = 2 if cy <= split_y else 1
            obj["tierName"] = "Tầng 2 (Trên)" if obj["tier"] == 2 else "Tầng 1 (Dưới)"

        def _calc_tier_stats(tier_id: int, tier_name: str, tier_objs: List[Dict]) -> Dict[str, Any]:
            prods = [o for o in tier_objs if not o.get("isEmptySlot", False)]
            empties = [o for o in tier_objs if o.get("isEmptySlot", False)]

            p_area = sum(float((o["box"][2] - o["box"][0]) * (o["box"][3] - o["box"][1])) for o in prods)
            e_area = sum(float((o["box"][2] - o["box"][0]) * (o["box"][3] - o["box"][1])) for o in empties)
            total_area = p_area + e_area

            num_p = len(prods)
            num_e = len(empties)

            if num_p == 0 and num_e == 0:
                d_pct = 0.0
                status = "Chưa có SP"
            elif num_p == 0:
                d_pct = 0.0
                status = "Out of Stock"
            elif num_e > 0:
                raw_ratio = (p_area / total_area) * 100.0 if total_area > 0 else 50.0
                d_pct = round(max(5.0, min(95.0, raw_ratio)), 1)
                if d_pct >= 70.0 and num_e <= 1:
                    status = "Well Stocked"
                elif d_pct >= 35.0:
                    status = "Normal"
                else:
                    status = "Low Stock"
            else:
                d_pct = min(95.0, 65.0 + num_p * 8.0) if num_p >= 2 else 70.0
                status = "Well Stocked" if d_pct >= 70.0 else "Normal"

            return {
                "tierId": tier_id,
                "tierName": tier_name,
                "densityPct": round(d_pct, 1),
                "emptyPercentage": round(max(0.0, 100.0 - d_pct), 1),
                "stockStatus": status,
                "productCount": num_p,
                "emptyCount": num_e,
                "totalObjects": len(tier_objs)
            }

        t2_objs = [o for o in detected_objects if o.get("tier") == 2]
        t1_objs = [o for o in detected_objects if o.get("tier") == 1]

        t2_stats = _calc_tier_stats(2, "Tầng 2 (Trên)", t2_objs)
        t1_stats = _calc_tier_stats(1, "Tầng 1 (Dưới)", t1_objs)

        tier_summary = {
            "tierCount": 2 if (t1_objs and t2_objs) else (1 if detected_objects else 0),
            "isMultiTier": is_multi_tier,
            "splitY": round(split_y, 1) if split_y is not None else None,
            "tier1": t1_stats,
            "tier2": t2_stats
        }

        return detected_objects, split_y, tier_summary

    def _detect_shelf_color_ratio(self, frame: np.ndarray, product_objects: List[Dict]) -> float:
        """
        Detects the ratio of light orange/beige shelf-color pixels in the frame,
        EXCLUDING areas covered by detected products.
        Returns a float 0.0 - 1.0 (0 = no shelf color visible, 1 = entire frame is bare shelf).
        """
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # HSV range for light orange/beige shelf surface (tunable)
        # Covers: cream, light orange, beige, tan, light brown shelf metal
        lower1 = np.array([8, 25, 120])    # Lower orange/beige
        upper1 = np.array([30, 180, 255])   # Upper orange/beige
        lower2 = np.array([0, 15, 150])     # Very light cream/white-ish beige
        upper2 = np.array([15, 100, 255])

        mask1 = cv2.inRange(hsv, lower1, upper1)
        mask2 = cv2.inRange(hsv, lower2, upper2)
        shelf_mask = cv2.bitwise_or(mask1, mask2)

        # Mask OUT product bounding boxes (we only care about empty areas)
        for obj in product_objects:
            x1, y1, x2, y2 = obj["box"]
            shelf_mask[y1:y2, x1:x2] = 0

        shelf_pixels = cv2.countNonZero(shelf_mask)
        total_pixels = float(h * w)

        return shelf_pixels / total_pixels if total_pixels > 0 else 0.0

    def render_hud_overlay(self, frame: np.ndarray, analysis: Dict[str, Any]) -> np.ndarray:
        """
        Draws modern HUD bounding boxes with Tier labels, Shelf Type Badge, Shelf Divider Line,
        and Multi-tier Density Gauges on the frame.
        """
        annotated = frame.copy()
        h, w = annotated.shape[:2]

        shelf_id = analysis.get("shelfId", 0)

        # 1. Draw ArUco Tag Highlights
        for abox in analysis.get("arucoBoxes", []):
            x1, y1, x2, y2 = abox["box"]
            tid = abox["tagId"]
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 3) # Neon Green
            tag_label = f"ARUCO TAG #{tid}"
            cv2.putText(annotated, tag_label, (x1, max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)

        # 2. Draw Shelf Divider Line (if multi-tier)
        split_y = analysis.get("splitY")
        if split_y is not None:
            sy = int(split_y)
            # Dashed/divider line with neon yellow
            cv2.line(annotated, (20, sy), (w - 20, sy), (0, 230, 255), 2, cv2.LINE_AA)
            div_text = "-- DUONG PHAN TANG KE (TIER DIVIDER) --"
            (tw, th), _ = cv2.getTextSize(div_text, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
            cx = (w - tw) // 2
            cv2.rectangle(annotated, (cx - 8, sy - th - 5), (cx + tw + 8, sy + 5), (20, 20, 25), -1)
            cv2.rectangle(annotated, (cx - 8, sy - th - 5), (cx + tw + 8, sy + 5), (0, 230, 255), 1)
            cv2.putText(annotated, div_text, (cx, sy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 230, 255), 1, cv2.LINE_AA)

        # 3. Draw Object Bounding Boxes with Tier Indicator & Product Names
        pil_img = Image.fromarray(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_img)

        for obj in analysis.get("detectedObjects", []):
            x1, y1, x2, y2 = obj["box"]
            label = obj.get("label", "Sản phẩm")
            conf = obj["confidence"]
            similarity = obj.get("similarity")
            is_empty = obj.get("isEmptySlot", False)
            tier_num = obj.get("tier", 0)
            tier_prefix = f"[T{tier_num}] " if tier_num > 0 else ""

            if is_empty:
                box_rgb = (255, 0, 0) # Red in RGB
                caption = remove_accents(f"{tier_prefix}HẾT HÀNG ({int(conf*100)}%)")
            else:
                box_rgb = (0, 140, 255) # Cyan/Orange in RGB
                score_pct = int(similarity * 100) if similarity is not None else int(conf * 100)
                caption = remove_accents(f"{tier_prefix}{label} ({score_pct}%)")

            # Draw box rectangle
            draw.rectangle((x1, y1, x2, y2), outline=box_rgb, width=2)

            # Label banner
            bbox = draw.textbbox((x1, y1), caption, font=self.font_main)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            banner_y1 = max(0, y1 - th - 8)
            banner_y2 = y1
            draw.rectangle((x1, banner_y1, x1 + tw + 10, banner_y2), fill=box_rgb)
            text_color = (0, 0, 0) if not is_empty else (255, 255, 255)
            draw.text((x1 + 4, banner_y1 + 2), caption, font=self.font_main, fill=text_color)

        annotated = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        # 4. Draw Top HUD Badge (Shelf Type, Tier Stats, & Latency)
        hud_bg = np.zeros((76, w, 3), dtype=np.uint8)
        hud_bg[:] = (20, 20, 25)
        # Alpha blend top HUD
        annotated[0:76, 0:w] = cv2.addWeighted(annotated[0:76, 0:w], 0.2, hud_bg, 0.8, 0)

        shelf_name = analysis.get("shelfCategory", "Quét Kệ Hàng")
        stock_status = analysis.get("stockStatus", "Normal")
        density_pct = analysis.get("densityPct", 0.0)
        inf_time = analysis.get("inferenceTimeMs", 0.0)
        total_objs = analysis.get("totalObjects", 0)

        tier1 = analysis.get("tier1") or {}
        tier2 = analysis.get("tier2") or {}
        t2_pct = tier2.get("densityPct", 0.0)
        t1_pct = tier1.get("densityPct", 0.0)
        t2_st = tier2.get("stockStatus", "--")
        t1_st = tier1.get("stockStatus", "--")

        # Shelf Title
        cv2.putText(annotated, remove_accents(f"SHELF: {shelf_name.upper()}"), (16, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)

        # Latency & Object count
        cv2.putText(annotated, remove_accents(f"YOLOv8 Latency: {inf_time}ms | Objects: {total_objs} (Đầy: {density_pct}%)"), (16, 56),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (180, 180, 180), 1, cv2.LINE_AA)

        # Status colors
        def _get_status_color(st):
            if st == "Well Stocked": return (0, 220, 100)
            if st == "Normal": return (0, 200, 255)
            if st == "Low Stock": return (0, 140, 255)
            return (0, 0, 255)

        # Draw Tier 2 Badge (Tầng Trên)
        cv2.rectangle(annotated, (w - 365, 8), (w - 190, 68), (35, 35, 45), -1)
        cv2.rectangle(annotated, (w - 365, 8), (w - 190, 68), _get_status_color(t2_st), 1)
        cv2.putText(annotated, f"T2 (TREN): {t2_pct}%", (w - 357, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 240, 255), 1, cv2.LINE_AA)
        cv2.putText(annotated, f"{t2_st}", (w - 357, 46),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, _get_status_color(t2_st), 1, cv2.LINE_AA)
        cv2.putText(annotated, f"{tier2.get('productCount', 0)} SP | {tier2.get('emptyCount', 0)} Trong", (w - 357, 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1, cv2.LINE_AA)

        # Draw Tier 1 Badge (Tầng Dưới)
        cv2.rectangle(annotated, (w - 180, 8), (w - 10, 68), (35, 35, 45), -1)
        cv2.rectangle(annotated, (w - 180, 8), (w - 10, 68), _get_status_color(t1_st), 1)
        cv2.putText(annotated, f"T1 (DUOI): {t1_pct}%", (w - 172, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 140), 1, cv2.LINE_AA)
        cv2.putText(annotated, f"{t1_st}", (w - 172, 46),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, _get_status_color(t1_st), 1, cv2.LINE_AA)
        cv2.putText(annotated, f"{tier1.get('productCount', 0)} SP | {tier1.get('emptyCount', 0)} Trong", (w - 172, 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1, cv2.LINE_AA)

        # 5. Draw Bottom Density Bar
        bar_y = h - 26
        bar_w = w - 40
        fill_w = int((density_pct / 100.0) * bar_w)

        # Background bar
        cv2.rectangle(annotated, (20, bar_y), (20 + bar_w, bar_y + 16), (40, 40, 40), -1)
        # Filled bar
        bar_fill_color = (0, 220, 100) if density_pct >= 60 else ((0, 200, 255) if density_pct >= 30 else (0, 0, 255))
        if fill_w > 0:
            cv2.rectangle(annotated, (20, bar_y), (20 + fill_w, bar_y + 16), bar_fill_color, -1)
        cv2.rectangle(annotated, (20, bar_y), (20 + bar_w, bar_y + 16), (150, 150, 150), 1)

        # Density Text
        shelf_empty_ratio = analysis.get("shelfColorRatio", 0.0)
        density_label = remove_accents(f"SHELF DENSITY: {density_pct}% ({stock_status}) | EMPTY SPACE: {shelf_empty_ratio}%")
        cv2.putText(annotated, density_label, (20, bar_y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

        return annotated
