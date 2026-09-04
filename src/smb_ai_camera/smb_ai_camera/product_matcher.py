import os
import re
import cv2
import numpy as np
import torch
import torch.nn as nn
from torchvision import models, transforms
from typing import Dict, List, Any, Tuple, Optional

class ProductFeatureMatcher:
    """
    Lightweight 2-Stage Product Re-Identification Engine using MobileNetV3-Small.
    Extracts L2-normalized visual embeddings and matches shelf products via Cosine Similarity.
    Allows arbitrary number of reference photos per product (front, angle, top-down).
    """

    DEFAULT_NAME_MAP = {
        # Kệ 4
        "ly_mi_life_cup": "Ly Mì Life Cup",
        "banh_com_nguyen_ninh": "Bánh Cốm Hà Nội",
        "banh_com": "Bánh Cốm Hà Nội",
        "mi_koreno_jumbo": "Mì Koreno Jumbo",
        "mi_koreno": "Mì Koreno Jumbo",
        "chao_gau_do": "Cháo Gấu Đỏ",
        "mi_gau_do": "Mì Gấu Đỏ",
        "mi_indomie": "Mì Trộn Indomie",
        "mi_3_mien": "Mì 3 Miền",
        "mi_a_one": "Mì A-One",
        "chao_an_lien": "Cháo Ăn Liền",

        # Kệ 1 (Đồ ăn vặt)
        "chocopie": "Bánh ChocoPie Orion",
        "banh_chocopie": "Bánh ChocoPie Orion",
        "banh_tet": "Bánh Tét Mini",
        "banh_tet_mini": "Bánh Tét Mini",
        "banh_chung": "Bánh Chưng Mini",
        "banh_chung_mini": "Bánh Chưng Mini",
        "dau_phong": "Hũ Đậu Phộng Tinh Nghệ",
        "vien_tinh_nghe": "Hũ Đậu Phộng Tinh Nghệ",
        "snack_lays": "Snack Lay's Khoai Tây",
        "oishi_snack": "Snack Oishi Bắp Cải",
        "pinattsu": "Đậu Phộng Pinattsu",
        "snack_mix": "Snack Mix Hỗn Hợp",
        "banh_mi_que": "Bánh Mì Que Giòn",

        # Kệ 2 (Nước giải khát)
        "coca_cola": "Coca Cola 330ml",
        "pepsi": "Pepsi 330ml",
        "sting": "Nước Tăng Lực Sting",
        "mirinda": "Mirinda Cam 330ml",
        "red_bull": "Nước Tăng Lực Red Bull",
        "nuoc_khoang_lavie": "Nước Khoáng Lavie",
        "heineken": "Bia Heineken Silver",
        "binh_nuoc": "Bình Nước Giữ Nhiệt",
        "chai_nhua": "Chai Nước Nhựa",
        "ca_nhua": "Ca Nhựa Uống Nước",
        "ly_nhua": "Ly Nhựa Dùng 1 Lần",

        # Kệ 3 (Tươi sống / Thực phẩm)
        "thit_bo": "Thịt Bò Tươi Sạch",
        "thit_heo": "Thịt Heo Tươi",
        "ca_chep": "Cá Chép Tươi Sống",
        "rau_muong": "Rau Muống Sạch VietGAP",

        # Kệ 5 (Gia dụng)
        "khan_uot_gau": "Khăn Ướt Gấu",
        "khan_uot_bumbo": "Khăn Ướt Bumbo",
        "to_an_com": "Tô Ăn Cơm Sứ",
        "tho_giu_nhiet": "Thố Giữ Nhiệt",
        "ong_tam": "Ống Tăm Gỗ",
        "tam_tre": "Tăm Tre Tự Nhiên",
        "mang_boc_thuc_pham": "Màng Bọc Thực Phẩm Food Wrap",
        "food_wrap": "Màng Bọc Thực Phẩm Food Wrap",

        # Kệ 6 (Gia vị & Trà)
        "hu_gia_vi_vang": "Hũ Gia Vị Vàng",
        "hu_gia_vi_do": "Nước Tương Chin-Su",
        "nuoc_tuong_chinsu": "Nước Tương Chin-Su",
        "chin_su": "Nước Tương Chin-Su",
        "nuoc_tuong_maggi": "Nước Tương Maggi",
        "maggi": "Nước Tương Maggi",
        "sa_te_cay": "Sa Tế Tôm Cay",
        "sa_te": "Sa Tế Tôm Cay",
        "muoi_ot_chanh": "Muối Ớt Chanh Nha Trang",
        "dau_me_meizan": "Dầu Mè Thơm Meizan",
        "dau_me": "Dầu Mè Thơm Meizan",
        "hu_muoi_ot_tay_ninh": "Hũ Muối Ớt Tây Ninh",
        "muoi_tay_ninh": "Hũ Muối Ớt Tây Ninh",
        "tieu_den_phu_quoc": "Tiêu Đen Phú Quốc",
        "tieu_phu_quoc": "Tiêu Đen Phú Quốc",
        "tra_ngoc_an": "Trà Lài Ngọc An",
        "tra_thien_thao": "Trà Thiên Thảo",
    }

    def __init__(self, base_dir: str = "reference_products", device: Optional[str] = None):
        self.base_dir = os.path.abspath(base_dir)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[ProductMatcher] Initializing on device: {self.device.upper()}...")

        # Pretrained MobileNetV3-Small feature extractor (576-dim output)
        base_model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
        base_model.eval()
        self.extractor = nn.Sequential(
            base_model.features,
            base_model.avgpool,
            nn.Flatten()
        ).to(self.device)

        # Image preprocessing pipeline for ImageNet-pretrained network
        self.preprocess = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

        # Cache reference embeddings: {shelf_id: [ {productId, productName, embedding}, ... ]}
        self.reference_embeddings: Dict[int, List[Dict[str, Any]]] = {}
        self.load_all_reference_images()

    def _clean_product_id(self, filename: str) -> str:
        """Strips file extension and trailing numeric indices (e.g., 'ly_mi_life_cup_2.jpg' -> 'ly_mi_life_cup')"""
        name_no_ext = os.path.splitext(filename)[0]
        cleaned = re.sub(r'_\d+$', '', name_no_ext)
        return cleaned.lower()

    def _get_display_name(self, product_id: str) -> str:
        if product_id in self.DEFAULT_NAME_MAP:
            return self.DEFAULT_NAME_MAP[product_id]
        # Capitalize nicely if not in predefined map
        return " ".join(w.capitalize() for w in product_id.replace("_", " ").split())

    @torch.no_grad()
    def extract_embedding(self, img_bgr: np.ndarray) -> np.ndarray:
        """Extracts an L2-normalized 576-dim vector from a BGR OpenCV image."""
        if img_bgr is None or img_bgr.size == 0:
            return np.zeros(576, dtype=np.float32)

        # Convert BGR to RGB
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        tensor = self.preprocess(img_rgb).unsqueeze(0).to(self.device)
        feat = self.extractor(tensor).cpu().numpy().flatten()

        # L2 normalization
        norm = np.linalg.norm(feat)
        if norm > 0:
            feat = feat / norm
        return feat.astype(np.float32)

    def load_all_reference_images(self):
        """Scans reference_products/shelf_1..6/ and computes embeddings for all photos."""
        self.reference_embeddings.clear()
        total_photos = 0

        for shelf_id in range(1, 7):
            shelf_folder = os.path.join(self.base_dir, f"shelf_{shelf_id}")
            os.makedirs(shelf_folder, exist_ok=True)
            self.reference_embeddings[shelf_id] = []

            for fname in os.listdir(shelf_folder):
                if not fname.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    continue

                fpath = os.path.join(shelf_folder, fname)
                img = cv2.imread(fpath)
                if img is None:
                    continue

                prod_id = self._clean_product_id(fname)
                prod_name = self._get_display_name(prod_id)
                emb = self.extract_embedding(img)

                self.reference_embeddings[shelf_id].append({
                    "productId": prod_id,
                    "productName": prod_name,
                    "filename": fname,
                    "embedding": emb
                })
                total_photos += 1

        print(f"[ProductMatcher] Preloaded {total_photos} reference images across 6 shelves.")

    def match_crop(
        self,
        crop_bgr: np.ndarray,
        shelf_id: Optional[int] = None,
        similarity_threshold: float = 0.40
    ) -> Dict[str, Any]:
        """
        Matches a cropped bounding box against the reference products of the designated shelf.
        If shelf_id is None or 0, searches across all active shelves.
        """
        if crop_bgr is None or crop_bgr.size == 0:
            return {
                "productName": "Sản Phẩm",
                "productId": "unknown",
                "similarity": 0.0,
                "isMatched": False
            }

        crop_emb = self.extract_embedding(crop_bgr)

        # Determine candidate reference list
        candidates: List[Dict[str, Any]] = []
        if shelf_id and shelf_id in self.reference_embeddings and len(self.reference_embeddings[shelf_id]) > 0:
            candidates = self.reference_embeddings[shelf_id]
        else:
            # Fallback: search across all shelves if specific shelf has no reference images
            for s_id in range(1, 7):
                candidates.extend(self.reference_embeddings.get(s_id, []))

        if not candidates:
            return {
                "productName": "Sản Phẩm",
                "productId": "generic",
                "similarity": 1.0,
                "isMatched": True
            }

        # Calculate max similarity grouped by unique product
        prod_scores: Dict[str, Tuple[str, float]] = {} # prod_id: (prod_name, max_sim)

        for cand in candidates:
            sim = float(np.dot(crop_emb, cand["embedding"]))
            p_id = cand["productId"]
            p_name = cand["productName"]

            if p_id not in prod_scores or sim > prod_scores[p_id][1]:
                prod_scores[p_id] = (p_name, sim)

        # Pick best product
        best_pid = max(prod_scores, key=lambda k: prod_scores[k][1])
        best_name, best_sim = prod_scores[best_pid]

        # Cross-shelf Fallback: If designated shelf match is moderate or weak (< 0.85),
        # check if another shelf has a decisive match (> 0.70 and significantly higher than best_sim).
        # This gracefully handles misplaced goods or when testing with an accidental ArUco tag from another shelf.
        if best_sim < 0.85 and shelf_id is not None:
            all_cands = []
            for s_id in range(1, 7):
                if s_id != shelf_id:
                    all_cands.extend(self.reference_embeddings.get(s_id, []))
            if all_cands:
                alt_scores: Dict[str, Tuple[str, float]] = {}
                for cand in all_cands:
                    sim = float(np.dot(crop_emb, cand["embedding"]))
                    p_id = cand["productId"]
                    p_name = cand["productName"]
                    if p_id not in alt_scores or sim > alt_scores[p_id][1]:
                        alt_scores[p_id] = (p_name, sim)
                if alt_scores:
                    alt_pid = max(alt_scores, key=lambda k: alt_scores[k][1])
                    alt_name, alt_sim = alt_scores[alt_pid]
                    if alt_sim >= 0.70 and alt_sim > (best_sim + 0.08):
                        best_pid, best_name, best_sim = alt_pid, alt_name, alt_sim

        is_matched = (best_sim >= similarity_threshold)

        return {
            "productName": best_name if is_matched else "Sản Phẩm Khác",
            "productId": best_pid if is_matched else "unknown",
            "similarity": round(best_sim, 3),
            "isMatched": is_matched
        }
