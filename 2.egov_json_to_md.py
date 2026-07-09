"""
egov_json_to_md.py
==================
e-Gov 法令API (Version 2) の JSON ファイルを Markdown (.md) に変換するスクリプト。

【使い方】
1. e-Gov 法令API v2 から JSON をダウンロードし、このスクリプトと同じフォルダに置く。
   例: https://laws.e-gov.go.jp/api/2/law_data/405AC0000000088?response_format=json

2. このスクリプトを実行する:
   python egov_json_to_md.py

3. 同フォルダ内に .md ファイルが出力される。

【対応 JSON 形式】
- e-Gov 法令API v2 の response_format=json レスポンス
- tag / attr / children のネスト構造を持つもの
"""

import json
import sys
from pathlib import Path


# ─────────────────────────────────────────────
# テキスト抽出ユーティリティ
# ─────────────────────────────────────────────

def get_text(node) -> str:
    """ノードから純テキストを再帰的に結合して返す。"""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(get_text(c) for c in node)
    if isinstance(node, dict):
        return get_text(node.get("children", []))
    return ""


def find_all(node, tag: str) -> list:
    """ツリーを再帰探索して指定タグのノードをすべて返す。"""
    results = []
    if isinstance(node, dict):
        if node.get("tag") == tag:
            results.append(node)
        for child in node.get("children", []):
            results.extend(find_all(child, tag))
    elif isinstance(node, list):
        for item in node:
            results.extend(find_all(item, tag))
    return results


def find_first(node, tag: str):
    """最初に見つかった指定タグのノードを返す（なければ None）。"""
    results = find_all(node, tag)
    return results[0] if results else None


# ─────────────────────────────────────────────
# 各要素を Markdown に変換
# ─────────────────────────────────────────────

def convert_sentence(node) -> str:
    """Sentence / Ruby など行内要素を Markdown 文字列に変換。"""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(convert_sentence(c) for c in node)
    if not isinstance(node, dict):
        return ""
    tag = node.get("tag", "")
    children = node.get("children", [])
    if tag == "Ruby":
        base = find_first(node, "Rb")
        rt = find_first(node, "Rt")
        base_text = get_text(base) if base else get_text(children)
        rt_text = get_text(rt) if rt else ""
        # Markdown には公式のルビ記法がないため「基字（読み）」形式で表現
        return f"{base_text}（{rt_text}）" if rt_text else base_text
    # その他のインライン要素はそのまま子を展開
    return "".join(convert_sentence(c) for c in children)


def render_paragraph(para_node) -> str:
    """Paragraph（項）を Markdown 文字列に変換。

    TableStruct が含まれる場合、直前の文（ParagraphSentence）と表を
    一体で出力する。これにより準用条文の読替え表などで文脈が失われない。
    """
    num_node = find_first(para_node, "ParagraphNum")
    num_label = get_text(num_node).strip() if num_node else ""

    # 子要素を順番通りに処理（文→表の順序を保持）
    blocks = []
    sentences_buf = []

    def flush_sentences():
        text = "".join(sentences_buf).strip()
        sentences_buf.clear()
        if text:
            blocks.append(text)

    for child in para_node.get("children", []):
        if not isinstance(child, dict):
            continue
        tag = child.get("tag", "")
        if tag == "ParagraphSentence":
            for s in child.get("children", []):
                if isinstance(s, dict) and s.get("tag") == "Sentence":
                    sentences_buf.append(convert_sentence(s.get("children", [])))
        elif tag in ("Item", "Subitem1"):
            flush_sentences()
            blocks.append(render_item(child, depth=0))
        elif tag == "TableStruct":
            # 文をフラッシュしてから表を追加（前後文脈を保持）
            flush_sentences()
            blocks.append(render_table_struct(child))

    flush_sentences()

    # 項番号を先頭に付与
    lines = []
    if blocks:
        first = blocks[0]
        if num_label and num_label not in ("１", "1"):
            lines.append(f"**{num_label}**　{first}")
        else:
            lines.append(first)
        lines.extend(blocks[1:])

    return "\n\n".join(l for l in lines if l)


def _render_column_sentence(sentence_node) -> str:
    """
    *Sentence 直下の Column 要素（欄）を処理する。

    Column タグは e-Gov XML で「括弧書きの前後を分割する」用途に使われる。
    例: Column1="…にあつては、（" / Column2="）内の単位数とする。"
    これらは単純連結することで本来の文を復元する。

    Column がない場合は通常の Sentence として処理。
    """
    cols = [c for c in sentence_node.get("children", [])
            if isinstance(c, dict) and c.get("tag") == "Column"]
    if cols:
        # Column はすべて単純連結（括弧書きパターンの復元）
        return "".join(get_text(c) for c in cols).strip()
    # Column がない場合は通常の Sentence を連結
    parts = []
    for s in sentence_node.get("children", []):
        if isinstance(s, dict) and s.get("tag") == "Sentence":
            parts.append(convert_sentence(s.get("children", [])))
    return "".join(parts).strip()


def render_item(item_node, depth: int = 0) -> str:
    """Item / Subitem（号・細号）を Markdown リスト行に変換。"""
    indent = "  " * depth
    tag = item_node.get("tag", "Item")

    # タイトルタグ・文タグを決定
    if tag == "Item":
        title_tag = "ItemTitle"
        sentence_tag = "ItemSentence"
    else:
        # Subitem1, Subitem2, ... → 深さに関係なくタグ名から数字を取る
        import re
        m = re.search(r"\d+", tag)
        n = m.group() if m else str(depth)
        title_tag = f"Subitem{n}Title"
        sentence_tag = f"Subitem{n}Sentence"

    title_node = find_first(item_node, title_tag)
    sentence_node = find_first(item_node, sentence_tag)

    title_text = get_text(title_node).strip() if title_node else ""
    sentence_text = _render_column_sentence(sentence_node) if sentence_node else ""

    line = f"{indent}- {title_text}　{sentence_text}".rstrip("　").strip()

    # 子要素を処理（子号 + TableStruct）
    sub_lines = []
    sub_item_tags = {"Item", "Subitem1", "Subitem2", "Subitem3",
                     "Subitem4", "Subitem5", "Subitem6"}
    for child in item_node.get("children", []):
        if not isinstance(child, dict):
            continue
        ctag = child.get("tag", "")
        if ctag in sub_item_tags:
            sub_lines.append(render_item(child, depth + 1))
        elif ctag == "TableStruct":
            # 号の中に表が入っている場合（インデントを合わせて挿入）
            table_md = render_table_struct(child)
            # 各行にインデントを付ける
            indented = "\n".join(
                (indent + "  " + l if l.strip() else l)
                for l in table_md.splitlines()
            )
            sub_lines.append(indented)

    return "\n".join([line] + sub_lines)


# ─────────────────────────────────────────────
# 表（TableStruct）変換
# ─────────────────────────────────────────────

def _col_text(col_node) -> str:
    """
    TableColumn の中身をテキストに変換。

    通常: Sentence のみ
    特殊: Item / Subitem1 が直接入っている（表セルが条文リスト）
          → render_item で展開して改行結合
    """
    item_tags = {"Item", "Subitem1", "Subitem2", "Subitem3",
                 "Subitem4", "Subitem5", "Subitem6"}
    children = col_node.get("children", [])

    # Item/Subitem が含まれるかチェック
    has_items = any(
        isinstance(c, dict) and c.get("tag") in item_tags
        for c in children
    )

    if has_items:
        # 条文リスト形式のセル → render_item で各行を展開
        parts = []
        for child in children:
            if not isinstance(child, dict):
                continue
            ctag = child.get("tag", "")
            if ctag in item_tags:
                parts.append(render_item(child, depth=0))
            elif ctag == "Sentence":
                parts.append(convert_sentence(child.get("children", [])))
            elif ctag == "Paragraph":
                parts.append(render_paragraph(child))
            else:
                t = get_text(child).strip()
                if t:
                    parts.append(t)
        return "\n".join(p for p in parts if p)

    # 通常セル
    parts = []
    for child in children:
        if not isinstance(child, dict):
            if isinstance(child, str):
                parts.append(child)
            continue
        tag = child.get("tag", "")
        if tag == "Sentence":
            parts.append(convert_sentence(child.get("children", [])))
        elif tag == "Paragraph":
            parts.append(render_paragraph(child))
        else:
            parts.append(get_text(child))
    return "".join(parts).strip()


def _build_grid(table_node) -> list[list[dict]]:
    """
    TableRow/TableColumn を解析して 2D グリッドを構築する。

    各セルは {"text": str, "colspan": int, "rowspan": int, "is_placeholder": bool}
    rowspan/colspan 属性に加え、BorderTop/Bottom=none による暗黙的な縦結合も検出する。
    """
    rows_nodes = [c for c in table_node.get("children", [])
                  if isinstance(c, dict) and c.get("tag") == "TableRow"]
    if not rows_nodes:
        return []

    # まずグリッドの最大列数を推定（colspan を考慮）
    max_cols = max(
        sum(int(c.get("attr", {}).get("colspan", 1) or 1)
            for c in row.get("children", [])
            if isinstance(c, dict) and c.get("tag") == "TableColumn")
        for row in rows_nodes
    ) if rows_nodes else 1

    num_rows = len(rows_nodes)
    grid: list[list] = [[None] * max_cols for _ in range(num_rows)]

    for ri, row_node in enumerate(rows_nodes):
        col_nodes = [c for c in row_node.get("children", [])
                     if isinstance(c, dict) and c.get("tag") == "TableColumn"]
        ci_grid = 0
        for col_node in col_nodes:
            while ci_grid < max_cols and grid[ri][ci_grid] is not None:
                ci_grid += 1

            attr = col_node.get("attr", {})
            colspan = int(attr.get("colspan", 1) or 1)
            rowspan = int(attr.get("rowspan", 1) or 1)

            # ── Border暗黙結合の検出 ──
            # BorderBottom=none のセルは「下の行と視覚的に結合している」を意味する。
            # 対応する下の行の同列セルが BorderTop=none であれば rowspan=2 相当として扱う。
            if rowspan == 1 and attr.get("BorderBottom", "solid") == "none":
                # 次の行の同じ列位置のセルを確認
                if ri + 1 < num_rows:
                    next_cols = [c for c in rows_nodes[ri + 1].get("children", [])
                                 if isinstance(c, dict) and c.get("tag") == "TableColumn"]
                    # 簡易マッピング：次行の同インデックスのセル属性を確認
                    # (colspan考慮なしの近似。多段結合には対応しない)
                    ci_in_next = 0
                    for nc in next_cols:
                        if ci_in_next == ci_grid:
                            if nc.get("attr", {}).get("BorderTop", "solid") == "none":
                                rowspan = 2
                            break
                        ci_in_next += int(nc.get("attr", {}).get("colspan", 1) or 1)

            text = _col_text(col_node)
            cell = {"text": text, "colspan": colspan, "rowspan": rowspan, "is_placeholder": False}

            for dr in range(rowspan):
                for dc in range(colspan):
                    rr, cc = ri + dr, ci_grid + dc
                    if rr < num_rows and cc < max_cols:
                        if dr == 0 and dc == 0:
                            grid[rr][cc] = cell
                        else:
                            grid[rr][cc] = {"text": "", "colspan": 1, "rowspan": 1,
                                            "is_placeholder": True}
            ci_grid += colspan

    # None 残りを空セルで埋める
    for ri in range(num_rows):
        for ci in range(max_cols):
            if grid[ri][ci] is None:
                grid[ri][ci] = {"text": "", "colspan": 1, "rowspan": 1, "is_placeholder": False}

    return grid


# ─────────────────────────────────────────────
# LLM向け表レンダラー（グリッド正規化→エントリ展開）
# ─────────────────────────────────────────────

# 読替え表と判定するヘッダキーワード
_REPLACEMENT_TABLE_KEYWORDS = {"上欄", "中欄", "下欄"}
import re as _re
_ARTICLE_NUM_RE = _re.compile(r"第[一二三四五六七八九十百]+条")


def _detect_table_type(headers: list[str]) -> tuple[str, int]:
    """
    ヘッダ行の文字列から表の種類とヘッダ行数を判定する。

    戻り値: (table_type, header_rows)
      - table_type: "replacement" or "entry"
      - header_rows: ヘッダとして消費する先頭行数（0 or 1）

    判定ルール（上から順に評価）:
      1. ヘッダに「上欄/中欄/下欄」キーワードあり
         → replacement, header_rows=1
      2. 3列構成 + 先頭セルが条番号で始まる
         → replacement, header_rows=0（準用条文の読替え表・ヘッダなし型）
      3. 2列または3列構成（上記以外）
         → entry, header_rows=0（ヘッダなし対応表・仮列名「上欄/中欄/下欄」を使う）
         e-Gov 法令の多くは本文で「上欄/中欄/下欄」と説明される対応表が、JSON では
         ヘッダ行を持たずに2〜3列のデータだけで表現される。1行目をヘッダ消費すると
         データ欠落を起こすため、全行をデータとして扱う。
      4. それ以外（4列以上・1列、または1行目がすべて空 など）
         → entry, header_rows=1（従来通り1行目をヘッダ消費）

    注意:
      列数は headers の全長で判定する（空セルを除外した non_empty の長さではない）。
      空セルを除外して判定すると、2段ヘッダで rowspan により下段がプレースホルダー化
      した行（例: ['A','B','C','','','']）を「3列」と誤判定する不具合になる。
    """
    non_empty = [h.strip() for h in headers if h.strip()]
    header_set = set(non_empty)

    # 1行目がすべて空 → ヘッダ判定不能
    if not non_empty:
        return ("entry", 1)

    if header_set & _REPLACEMENT_TABLE_KEYWORDS:
        return ("replacement", 1)

    n_cols = len(headers)
    first_cell = headers[0].strip()

    # 2列・3列でヘッダ行を持たないと推定されるケース
    if n_cols in (2, 3) and first_cell:
        # 3列で先頭が条番号 → 読替え表
        if n_cols == 3 and _ARTICLE_NUM_RE.search(first_cell):
            return ("replacement", 0)
        # それ以外の2〜3列 → ヘッダなし対応表
        return ("entry", 0)

    return ("entry", 1)


def _normalize_grid_for_llm(grid: list[list[dict]]) -> list[list[str]]:
    """
    グリッドを正規化してフラットな2D文字列リストに変換する。

    rowspan/colspan で結合されていたセルの値をプレースホルダー位置に繰り返し埋め込む。
    空白のみのセルは空文字列に正規化する。
    """
    if not grid:
        return []

    num_rows = len(grid)
    num_cols = len(grid[0])
    flat = [[""] * num_cols for _ in range(num_rows)]

    # 実セルの値を書き込む
    for ri, row in enumerate(grid):
        for ci, cell in enumerate(row):
            if not cell.get("is_placeholder"):
                flat[ri][ci] = cell.get("text", "").strip()

    # rowspan プレースホルダー（上方向に遡って親の値を繰り返す）
    for ri, row in enumerate(grid):
        for ci, cell in enumerate(row):
            if cell.get("is_placeholder"):
                for look_r in range(ri - 1, -1, -1):
                    if not grid[look_r][ci].get("is_placeholder"):
                        flat[ri][ci] = flat[look_r][ci]
                        break

    # 全角スペースのみのセルを空文字に正規化
    return [
        [c if c.strip() else "" for c in row]
        for row in flat
    ]


def _detect_header_rows(flat: list[list[str]], grid: list[list[dict]]) -> int:
    """
    gridの生データからヘッダ行数を検出する。最大2段まで対応。

    2段ヘッダの条件（両方を満たす場合）:
      A) grid[0] に colspan > 1 の実セルが存在する
      B) grid[0]のplaceholder列に対応するgrid[1]のセルが「サブヘッダ」である
         = grid[1]の全セルが非placeholder かつ いずれも rowspan=1（データ行でない）
         かつ grid[1]の先頭セルが rowspan > 1 でない（rowspan=1 = データでなくヘッダ）

    配乗表のような「ヘッダ行1行・次行がrowspan付きデータ行」は1段ヘッダと判定。
    """
    if not grid or len(grid) < 2:
        return 1

    row0 = grid[0]
    row1 = grid[1]

    # A: grid[0]にcolspan>1の実セルがあるか
    has_colspan = any(
        cell.get("colspan", 1) > 1
        for cell in row0
        if isinstance(cell, dict) and not cell.get("is_placeholder")
    )
    if not has_colspan:
        return 1

    placeholder_cols = [ci for ci, cell in enumerate(row0) if cell.get("is_placeholder")]
    if not placeholder_cols:
        return 1

    # grid[1]の非placeholder先頭セルがrowspan>1 → 行全体がデータ行（配乗表パターン）
    first_real_in_row1 = next((c for c in row1 if not c.get("is_placeholder")), None)
    if first_real_in_row1 and first_real_in_row1.get("rowspan", 1) > 1:
        return 1

    # placeholder列に対応するgrid[1]のセルに値があるか
    any_subheader_value = any(
        ci < len(row1)
        and not row1[ci].get("is_placeholder")
        and row1[ci].get("text", "").strip()
        for ci in placeholder_cols
    )

    return 2 if any_subheader_value else 1


def _build_column_headers(flat: list[list[str]], header_rows: int,
                          grid: list[list[dict]] = None) -> list[str]:
    """
    ヘッダ行（1段 or 2段）から列ごとの最終列名リストを生成する。

    2段ヘッダの場合、gridのオリジナル情報からグループ名を取得する：
      - grid[0]の実セル（colspan>1）がカバーする列範囲 → グループ名
      - grid[0]の実セル（rowspan=2）がカバーする列 → 単独列名
      - grid[1]のサブ列名と組み合わせて「グループ名（サブ名）」に合成
      - サブ名が空の列はグループ名のみ使用
    """
    num_cols = len(flat[0])

    if header_rows == 1:
        # 1段ヘッダでもcolspanのplaceholder列（flat[0]が空）には
        # gridから親セルの値を補完する。colspan>1の場合は連番を付けて区別する。
        if grid:
            headers_1 = list(flat[0])
            row0_grid = grid[0]
            ci_grid = 0
            for cell in row0_grid:
                if cell.get("is_placeholder"):
                    ci_grid += 1
                    continue
                colspan = cell.get("colspan", 1)
                text = cell.get("text", "").strip()
                if colspan > 1:
                    # 複数列に広がるセル → 各列に連番付きで補完
                    for dc in range(colspan):
                        idx = ci_grid + dc
                        if idx < len(headers_1) and not headers_1[idx]:
                            headers_1[idx] = f"{text}{dc + 1}"
                    # 先頭列（実セル位置）も連番付きに統一
                    if ci_grid < len(headers_1):
                        headers_1[ci_grid] = f"{text}1"
                ci_grid += colspan
            return headers_1
        return list(flat[0])

    row1 = flat[1]

    # grid[0]から各列のグループ名を正確に取得
    # colspan展開されたplaceholder列にも親のグループ名を割り当てる
    col_group: list[str] = [""] * num_cols  # 列インデックス → グループ名
    col_is_standalone: list[bool] = [False] * num_cols  # rowspan列（単独）か

    if grid:
        row0_grid = grid[0]
        ci_grid = 0
        for cell in row0_grid:
            if cell.get("is_placeholder"):
                ci_grid += 1
                continue
            colspan = cell.get("colspan", 1)
            rowspan = cell.get("rowspan", 1)
            text = cell.get("text", "").strip()
            for dc in range(colspan):
                if ci_grid + dc < num_cols:
                    col_group[ci_grid + dc] = text
                    if colspan == 1 and rowspan > 1:
                        col_is_standalone[ci_grid + dc] = True
            ci_grid += colspan
    else:
        # gridなしのフォールバック
        col_group = list(flat[0])

    headers = []
    # グループ名ごとに何番目のサブ列かをカウント（空サブ名の連番付けに使用）
    group_sub_counter: dict[str, int] = {}

    for ci in range(num_cols):
        grp = col_group[ci]
        sub = row1[ci].strip() if ci < len(row1) else ""
        standalone = col_is_standalone[ci]

        if standalone or not grp:
            # rowspan単独列、またはグループ名なし → そのまま
            headers.append(grp or sub)
        elif not sub:
            # グループ名はあるがサブヘッダが空
            # → 同グループ内で唯一の空列か複数あるかで判断
            # 同グループ内に値のあるサブヘッダが存在するなら連番で補完
            grp_cols = [i for i in range(num_cols) if col_group[i] == grp]
            has_named_sub = any(
                (row1[i].strip() if i < len(row1) else "")
                for i in grp_cols
            )
            if has_named_sub:
                # 連番補完（例: 乗船履歴1, 乗船履歴2）
                cnt = group_sub_counter.get(grp, 0) + 1
                group_sub_counter[grp] = cnt
                headers.append(f"{grp}{cnt}")
            else:
                # グループ内に名前付きサブが一切ない → グループ名のみ
                headers.append(grp)
        elif grp != sub:
            # グループ名＋サブ名 → 合成
            headers.append(f"{grp}（{sub}）")
        else:
            headers.append(sub)

    return headers


def _render_entry_table(flat: list[list[str]], title: str = "",
                        grid: list[list[dict]] = None,
                        header_rows: int = None) -> str:
    """
    対応表（要件表・配乗表・併科試験表など）をLLM向けエントリ形式で出力する。

    header_rows:
      None  : grid から自動検出（1段 or 2段ヘッダ）
      0     : ヘッダ行なし。仮列名「上欄/中欄/下欄」(3列) または「列1/列2/…」を使い、
              全行をデータとして扱う。本文中の「上欄/中欄/下欄」記述と紐づけるため。

    2段ヘッダの例：
        列構成: [海技試験の種別] × [乗船履歴（船舶）] × [乗船履歴（期間）] × [乗船履歴（資格）] × [乗船履歴（職務）]
        エントリ:
        - 海技試験の種別=六級海技士（航海）試験, 乗船履歴（船舶）=総トン数五トン以上の船舶, 乗船履歴（期間）=二年以上, ...
    """
    if not flat:
        return ""

    parts = []
    if title:
        parts.append(f"**{title}**")

    # ── ヘッダなし対応表モード ──
    if header_rows == 0:
        num_cols = len(flat[0])
        # 仮列名を割り当てる
        if num_cols == 3:
            headers = ["上欄", "中欄", "下欄"]
        elif num_cols == 2:
            headers = ["上欄", "下欄"]
        else:
            headers = [f"列{i+1}" for i in range(num_cols)]

        parts.append("列構成: " + " × ".join(f"[{h}]" for h in headers))

        entry_lines = []
        for row in flat:
            if not any(c for c in row):
                continue
            pairs = []
            for h, v in zip(headers, row):
                v = v.strip()
                if v:
                    pairs.append(f"{h}={v}")
                else:
                    pairs.append(f"{h}=（なし）")
            if pairs:
                entry_lines.append("- " + ", ".join(pairs))

        if entry_lines:
            parts.append("エントリ:")
            parts.extend(entry_lines)

        return "\n".join(parts)

    # ── 通常モード（ヘッダ自動検出） ──
    detected_header_rows = _detect_header_rows(flat, grid) if grid else 1

    # 列名リストの生成（2段ヘッダ合成）
    headers = _build_column_headers(flat, detected_header_rows, grid=grid)

    # 列構成の宣言（重複除去せずに全列を列挙）
    non_empty_headers = [h for h in headers if h]
    if non_empty_headers:
        parts.append("列構成: " + " × ".join(f"[{h}]" for h in non_empty_headers))

    # データ行（ヘッダ行を除いた残り）をエントリとして展開
    entry_lines = []
    for row in flat[detected_header_rows:]:
        if not any(c for c in row):
            continue
        pairs = []
        for h, v in zip(headers, row):
            h = h.strip()
            v = v.strip()
            if not h:
                continue
            if v:
                pairs.append(f"{h}={v}")
            else:
                pairs.append(f"{h}=（なし）")
        if pairs:
            entry_lines.append("- " + ", ".join(pairs))

    if entry_lines:
        parts.append("エントリ:")
        parts.extend(entry_lines)

    return "\n".join(parts)


def _render_replacement_table(flat: list[list[str]], title: str = "",
                              header_rows: int = 1) -> str:
    """
    読替え表（準用条文の字句読替え）をLLM向け形式で出力する。

    列構成: [規定条番号] | [読替え前（中欄）] | [読替え後（下欄）]

    header_rows:
      1: 1行目をヘッダとして使う（「上欄/中欄/下欄」型）
      0: ヘッダ行なし。1行目から全てデータ（条番号始まり型）

    出力例:
        【読替え表】
        規定: 第三条の三第一項
          「法第十七条...」→「法第二十三条の二十九...」
          「登録海技免許講習」→「登録小型船舶教習所における...」
    """
    if not flat:
        return ""

    parts = []
    if title:
        parts.append(f"**{title}**")
    parts.append("【読替え表】")

    # 列インデックスを特定（上欄=規定、中欄=読替前、下欄=読替後）
    col_kijun = 0   # 規定条番号列
    col_before = 1  # 読替え前列
    col_after = 2   # 読替え後列

    if header_rows >= 1:
        headers = flat[0]
        for i, h in enumerate(headers):
            if "上欄" in h or "規定" in h:
                col_kijun = i
            elif "中欄" in h or "読替前" in h:
                col_before = i
            elif "下欄" in h or "読替後" in h:
                col_after = i

    # データ行をグループ化（同じ規定条番号をまとめる）
    current_kijun = None
    replacements = []  # (before, after) のリスト
    groups = []        # (kijun, [(before, after), ...]) のリスト

    for row in flat[header_rows:]:
        if not any(c for c in row):
            continue
        kijun  = row[col_kijun].strip()  if col_kijun  < len(row) else ""
        before = row[col_before].strip() if col_before < len(row) else ""
        after  = row[col_after].strip()  if col_after  < len(row) else ""

        if kijun and kijun != current_kijun:
            if current_kijun is not None:
                groups.append((current_kijun, replacements))
            current_kijun = kijun
            replacements = []

        if before or after:
            replacements.append((before, after))

    if current_kijun is not None:
        groups.append((current_kijun, replacements))

    for kijun, reps in groups:
        parts.append(f"規定: {kijun}")
        for before, after in reps:
            b = f"「{before}」" if before else "（空欄）"
            a = f"「{after}」"  if after  else "（空欄）"
            parts.append(f"  {b} → {a}")

    return "\n".join(parts)


def _table_col_has_items(table_node) -> bool:
    """TableColumn の直下に Item/Subitem が含まれるか判定。"""
    item_tags = {"Item", "Subitem1", "Subitem2", "Subitem3"}
    table_inner = find_first(table_node, "Table") or table_node
    for row in table_inner.get("children", []):
        if not isinstance(row, dict) or row.get("tag") != "TableRow":
            continue
        for col in row.get("children", []):
            if not isinstance(col, dict) or col.get("tag") != "TableColumn":
                continue
            for child in col.get("children", []):
                if isinstance(child, dict) and child.get("tag") in item_tags:
                    return True
    return False


def _render_table_as_list(table_node) -> str:
    """
    TableColumn内にItem/Subitemが入っている「条文リスト型」テーブルを
    テーブルではなく条文リストとして出力する。
    TableStruct 直下の Remarks（備考）も末尾に追加する。
    """
    title_node = find_first(table_node, "TableStructTitle")
    title = get_text(title_node).strip() if title_node else ""

    parts = []
    if title:
        parts.append(f"**{title}**")

    table_inner = find_first(table_node, "Table") or table_node
    for row in table_inner.get("children", []):
        if not isinstance(row, dict) or row.get("tag") != "TableRow":
            continue
        for col in row.get("children", []):
            if not isinstance(col, dict) or col.get("tag") != "TableColumn":
                continue
            item_tags = {"Item", "Subitem1", "Subitem2", "Subitem3",
                         "Subitem4", "Subitem5", "Subitem6"}
            for child in col.get("children", []):
                if not isinstance(child, dict):
                    continue
                ctag = child.get("tag", "")
                if ctag in item_tags:
                    parts.append(render_item(child, depth=0))
                elif ctag == "Sentence":
                    t = convert_sentence(child.get("children", [])).strip()
                    if t:
                        parts.append(t)
                elif ctag == "Paragraph":
                    parts.append(render_paragraph(child))
                else:
                    t = get_text(child).strip()
                    if t:
                        parts.append(t)

    # TableStruct 直下の Remarks を末尾に追加
    for child in table_node.get("children", []):
        if isinstance(child, dict) and child.get("tag") == "Remarks":
            r = _render_remarks(child)
            if r:
                parts.append(r)

    return "\n\n".join(p for p in parts if p)


def render_table(table_node) -> str:
    """
    TableStruct を LLM向けテキストに変換する。

    処理フロー:
      1. 条文リスト型（TableColumn内にItem）→ 箇条書き出力（既存ロジック）
      2. グリッド正規化（rowspan/colspan・Border暗黙結合を解消）
      3. 表タイプ判定（読替え表 or 対応表）
      4. タイプ別レンダラーでエントリ展開
    """
    title_node = find_first(table_node, "TableStructTitle")
    title = get_text(title_node).strip() if title_node else ""

    # ── 1. 条文リスト型の判定 ──
    if _table_col_has_items(table_node):
        return _render_table_as_list(table_node)

    table_inner = find_first(table_node, "Table") or table_node
    grid = _build_grid(table_inner)

    if not grid:
        raw = get_text(table_node).strip()
        return f"**{title}**\n\n```\n{raw}\n```" if raw else ""

    # ── 2. グリッド正規化 ──
    flat = _normalize_grid_for_llm(grid)

    if not flat or not flat[0]:
        return ""

    # ── 3. 表タイプ判定 ──
    headers = flat[0]
    table_type, header_rows = _detect_table_type(headers)

    # ── 4. タイプ別レンダラー ──
    if table_type == "replacement":
        table_md = _render_replacement_table(flat, title, header_rows=header_rows)
    else:
        # header_rows=0 のときは「ヘッダなし対応表」として明示渡し。
        # header_rows=1 のときは自動検出に任せる（2段ヘッダ対応のため）。
        entry_header_rows = 0 if header_rows == 0 else None
        table_md = _render_entry_table(flat, title, grid=grid,
                                       header_rows=entry_header_rows)

    # ── 5. TableStruct 直下の Remarks（備考）を末尾に追加 ──
    # JSON 構造上 Remarks は TableStruct の子として Table と並列に置かれる。
    remarks_parts = []
    for child in table_node.get("children", []):
        if isinstance(child, dict) and child.get("tag") == "Remarks":
            r = _render_remarks(child)
            if r:
                remarks_parts.append(r)

    if remarks_parts:
        return "\n\n".join([table_md] + remarks_parts) if table_md else "\n\n".join(remarks_parts)
    return table_md


def render_table_struct(node) -> str:
    """TableStruct ノードを render_table に渡すラッパー。"""
    return render_table(node)


# ─────────────────────────────────────────────
# 別表等（Appdx 系）変換
# ─────────────────────────────────────────────

# 各 Appdx タグの設定テーブル
# key: タグ名
# value: (タイトル子タグ, 見出しプレフィックス, テキスト変換可能か)
_APPDX_CONFIG = {
    # 本則附属
    "AppdxTable":  ("AppdxTableTitle",  "別表",     True),
    "AppdxNote":   ("AppdxNoteTitle",   "別記",     True),
    "AppdxStyle":  ("AppdxStyleTitle",  "別記様式", False),
    "AppdxFig":    ("AppdxFigTitle",    "別図",     False),
    "Appdx":       ("AppdxTitle",       "付録",     True),
    "AppdxFormat": ("AppdxFormatTitle", "別記書式", False),
    # 附則附属
    "SupplProvisionAppdxTable": ("SupplProvisionAppdxTableTitle", "附則別表",  True),
    "SupplProvisionAppdxStyle": ("SupplProvisionAppdxStyleTitle", "附則様式",  False),
    "SupplProvisionAppdx":      ("SupplProvisionAppdxTitle",      "附則付録",  True),
}


def _render_remarks(node) -> str:
    """
    Remarks（備考）をテキスト化。RemarksLabel・Item号リストを含む複雑な備考に対応。

    出力フォーマット:
        **備考**
        - １　…
        - ２　…
    """
    label = ""
    lines = []
    for child in node.get("children", []):
        if not isinstance(child, dict):
            if isinstance(child, str) and child.strip():
                lines.append(child.strip())
            continue
        tag = child.get("tag", "")
        if tag == "RemarksLabel":
            label = get_text(child).strip()
        elif tag == "Sentence":
            lines.append(convert_sentence(child.get("children", [])))
        elif tag == "Paragraph":
            lines.append(render_paragraph(child))
        elif tag == "Item":
            lines.append(render_item(child, depth=0))
        else:
            t = get_text(child).strip()
            if t:
                lines.append(t)

    body = "\n".join(l for l in lines if l)
    if not body and not label:
        return ""

    prefix = label if label else "備考"
    header = f"**{prefix}**"
    return f"{header}\n{body}" if body else header


def _render_note_struct(node) -> str:
    """NoteStruct（記項目）を変換。別記（AppdxNote）の中身。"""
    parts = []
    for child in node.get("children", []):
        if not isinstance(child, dict):
            continue
        tag = child.get("tag", "")
        if tag == "NoteStructTitle":
            parts.append(f"**{get_text(child).strip()}**")
        elif tag == "Note":
            # Note の中には Paragraph, Sentence, TableStruct などが入る
            for nc in child.get("children", []):
                if not isinstance(nc, dict):
                    continue
                nt = nc.get("tag", "")
                if nt == "Paragraph":
                    parts.append(render_paragraph(nc))
                elif nt == "TableStruct":
                    parts.append(render_table_struct(nc))
                elif nt == "Sentence":
                    parts.append(convert_sentence(nc.get("children", [])))
                else:
                    t = get_text(nc).strip()
                    if t:
                        parts.append(t)
        elif tag == "Remarks":
            r = _render_remarks(child)
            if r:
                parts.append(r)
        elif tag == "TableStruct":
            parts.append(render_table_struct(child))
        elif tag == "FigStruct":
            parts.append("> *〔図：テキスト変換不可〕*")
    return "\n\n".join(p for p in parts if p)


def _render_appdx_convertible(appdx_node) -> str:
    """テキスト変換可能な Appdx 系ノードの中身をレンダリング。"""
    parts = []
    for child in appdx_node.get("children", []):
        if not isinstance(child, dict):
            continue
        tag = child.get("tag", "")
        # タイトル・関係条番号はヘッダで処理済みなのでスキップ
        if tag.endswith("Title") or tag == "RelatedArticleNum":
            continue
        if tag == "TableStruct":
            parts.append(render_table_struct(child))
        elif tag == "NoteStruct":
            parts.append(_render_note_struct(child))
        elif tag == "FigStruct":
            parts.append("> *〔図：テキスト変換不可〕*")
        elif tag == "StyleStruct":
            parts.append("> *〔様式：テキスト変換不可〕*")
        elif tag == "FormatStruct":
            parts.append("> *〔書式：テキスト変換不可〕*")
        elif tag == "Remarks":
            r = _render_remarks(child)
            if r:
                parts.append(r)
        elif tag == "Paragraph":
            parts.append(render_paragraph(child))
        elif tag == "Article":
            parts.append(render_article(child))
        elif tag in ("Item", "Subitem1"):
            # AppdxTable直下にItem→Subitem1→TableStructという構造がある場合
            parts.append(_render_appdx_item(child))
        else:
            t = get_text(child).strip()
            if t:
                parts.append(t)
    return "\n\n".join(p for p in parts if p)


def _render_appdx_item(item_node) -> str:
    """
    AppdxTable直下のItem/Subitem1を再帰的にレンダリング。
    Subitem1Title（一・二・三…）＋Subitem1Sentence（説明文）＋TableStructを
    見出し付きセクションとして出力する。
    """
    parts = []
    tag = item_node.get("tag", "")

    # タイトルと文を取得
    title_tag = "ItemTitle" if tag == "Item" else "Subitem1Title"
    sentence_tag = "ItemSentence" if tag == "Item" else "Subitem1Sentence"

    title_node = find_first(item_node, title_tag)
    sentence_node = find_first(item_node, sentence_tag)

    title_text = get_text(title_node).strip() if title_node else ""
    sentence_text = ""
    if sentence_node:
        for s in sentence_node.get("children", []):
            if isinstance(s, dict) and s.get("tag") == "Sentence":
                sentence_text += convert_sentence(s.get("children", []))
    sentence_text = sentence_text.strip()

    # 見出し行（例:「一　海技士（航海）の資格に係る海技試験」）
    heading = ""
    if title_text and sentence_text:
        heading = f"**{title_text}　{sentence_text}**"
    elif sentence_text:
        heading = f"**{sentence_text}**"
    elif title_text:
        heading = f"**{title_text}**"
    if heading:
        parts.append(heading)

    # 子ノードを処理
    for child in item_node.get("children", []):
        if not isinstance(child, dict):
            continue
        ctag = child.get("tag", "")
        if ctag in (title_tag, sentence_tag):
            continue  # 上で処理済み
        if ctag == "TableStruct":
            parts.append(render_table_struct(child))
        elif ctag in ("Item", "Subitem1", "Subitem2"):
            parts.append(_render_appdx_item(child))
        elif ctag == "Remarks":
            r = _render_remarks(child)
            if r:
                parts.append(r)
        elif ctag == "Paragraph":
            parts.append(render_paragraph(child))
        else:
            t = get_text(child).strip()
            if t:
                parts.append(t)

    return "\n\n".join(p for p in parts if p)


def render_appdx(appdx_node, heading_level: int = 2) -> str:
    """
    任意の Appdx 系ノードを Markdown に変換する統合レンダラー。

    heading_level: ## なら 2、附則内なら 3 など。
    """
    tag = appdx_node.get("tag", "")
    config = _APPDX_CONFIG.get(tag)
    if config is None:
        # 未知のタグは生テキスト
        return get_text(appdx_node).strip()

    title_child_tag, default_label, is_convertible = config
    hashes = "#" * heading_level

    # ─ ヘッダ部分 ─
    title_node = find_first(appdx_node, title_child_tag)
    title = get_text(title_node).strip() if title_node else default_label

    related_node = find_first(appdx_node, "RelatedArticleNum")
    related = get_text(related_node).strip() if related_node else ""

    header = f"{hashes} {title}"
    if related:
        header += f"\n{related}"

    # ─ 中身 ─
    if is_convertible:
        body = _render_appdx_convertible(appdx_node)
    else:
        # 変換不可：種別に応じた注記を出す
        kind_map = {
            "AppdxStyle":             "別記様式",
            "AppdxFig":               "別図",
            "AppdxFormat":            "別記書式",
            "SupplProvisionAppdxStyle": "附則様式",
        }
        kind = kind_map.get(tag, "非テキストコンテンツ")
        body = f"> *〔{kind}：テキスト変換不可。原典 JSON を参照してください〕*"

        # 変換不可でも Remarks（備考）だけは出せる
        for child in appdx_node.get("children", []):
            if isinstance(child, dict) and child.get("tag") == "Remarks":
                r = _render_remarks(child)
                if r:
                    body += f"\n\n{r}"

    parts = [header]
    if body:
        parts.append(body)
    return "\n\n".join(parts)


def render_article(article_node) -> str:
    """Article（条）を Markdown に変換。"""
    lines = []
    caption_node = find_first(article_node, "ArticleCaption")
    title_node = find_first(article_node, "ArticleTitle")
    caption = get_text(caption_node).strip() if caption_node else ""
    title = get_text(title_node).strip() if title_node else ""

    heading = title if not caption else f"{title}（{caption}）"
    lines.append(f"### {heading}")

    for child in article_node.get("children", []):
        if not isinstance(child, dict):
            continue
        tag = child.get("tag", "")
        if tag == "Paragraph":
            para_md = render_paragraph(child)
            if para_md:
                lines.append(para_md)
        elif tag == "TableStruct":
            lines.append(render_table_struct(child))

    return "\n\n".join(l for l in lines if l)


def render_section(section_node, level: int = 2) -> str:
    """Section / Chapter / Part などセクション系を Markdown に変換。"""
    lines = []
    hashes = "#" * level

    # タイトル取得（SectionTitle / ChapterTitle / PartTitle など）
    title = ""
    for child in section_node.get("children", []):
        if isinstance(child, dict) and child.get("tag", "").endswith("Title"):
            title = get_text(child).strip()
            break

    if title:
        lines.append(f"{hashes} {title}")

    # 子ノードを再帰処理
    for child in section_node.get("children", []):
        if not isinstance(child, dict):
            continue
        tag = child.get("tag", "")
        if tag in ("Part", "Chapter", "Section", "Subsection", "Division"):
            sublevel = level + 1
            lines.append(render_section(child, sublevel))
        elif tag == "Article":
            lines.append(render_article(child))
        elif tag == "Paragraph":
            lines.append(render_paragraph(child))
        elif tag == "TableStruct":
            lines.append(render_table_struct(child))

    return "\n\n".join(l for l in lines if l)


# ─────────────────────────────────────────────
# JSON → Markdown メイン変換
# ─────────────────────────────────────────────

def json_to_markdown(data: dict) -> str:
    """e-Gov API v2 JSON 全体を Markdown 文字列に変換。"""
    md_parts = []

    # ─ メタ情報を取得 ─
    law_info = data.get("law_info", {})
    law_full_text = data.get("law_full_text", {})

    # v2 レスポンス構造の正規化
    # トップレベルに "law_full_text" がある場合と "Law" ノードが直接ある場合の両方に対応
    law_node = None
    if law_full_text:
        law_node = find_first(law_full_text, "Law") or law_full_text
    else:
        law_node = find_first(data, "Law") or data

    # 法令名・番号
    law_title_node = find_first(law_node, "LawTitle")
    law_num_node = find_first(law_node, "LawNum")
    law_title = get_text(law_title_node).strip() if law_title_node else law_info.get("law_title", "（法令名不明）")
    law_num = get_text(law_num_node).strip() if law_num_node else law_info.get("law_num", "")

    md_parts.append(f"# {law_title}")
    if law_num:
        md_parts.append(f"**{law_num}**")

    # 追加メタ情報（v2 law_info）
    meta_fields = [
        ("law_type", "法令種別"),
        ("promulgation_date", "公布日"),
        ("enforcement_date", "施行日"),
    ]
    meta_lines = []
    for key, label in meta_fields:
        val = law_info.get(key, "")
        if val:
            meta_lines.append(f"- **{label}**: {val}")
    if meta_lines:
        md_parts.append("\n".join(meta_lines))

    # ─ 本文を変換 ─
    law_body = find_first(law_node, "LawBody")
    if not law_body:
        # フォールバック: LawBody がない場合はノード全体を探索
        law_body = law_node

    # 前文（EnactStatement）
    enact_node = find_first(law_body, "EnactStatement")
    if enact_node:
        enact_text = get_text(enact_node).strip()
        if enact_text:
            md_parts.append(f"---\n\n{enact_text}\n\n---")

    # 目次（TOC）
    toc_node = find_first(law_body, "TOC")
    if toc_node:
        md_parts.append("## 目次\n\n*（目次は本文の章立てを参照）*")

    # 本則（MainProvision）
    main_provision = find_first(law_body, "MainProvision")
    if main_provision:
        for child in main_provision.get("children", []):
            if not isinstance(child, dict):
                continue
            tag = child.get("tag", "")
            if tag in ("Part", "Chapter", "Section", "Subsection", "Division"):
                md_parts.append(render_section(child, level=2))
            elif tag == "Article":
                md_parts.append(render_article(child))
            elif tag == "Paragraph":
                md_parts.append(render_paragraph(child))
            elif tag == "TableStruct":
                md_parts.append(render_table_struct(child))

    # 附則（SupplProvision）
    for suppl in find_all(law_body, "SupplProvision"):
        label_node = find_first(suppl, "SupplProvisionLabel")
        label = get_text(label_node).strip() if label_node else "附則"
        amend_num = suppl.get("attr", {}).get("AmendLawNum", "")
        heading = f"## {label}"
        if amend_num:
            heading += f"（{amend_num}）"
        md_parts.append(heading)

        for child in suppl.get("children", []):
            if not isinstance(child, dict):
                continue
            tag = child.get("tag", "")
            if tag == "Article":
                md_parts.append(render_article(child))
            elif tag == "Paragraph":
                md_parts.append(render_paragraph(child))
            elif tag in ("Chapter", "Section", "Subsection", "Division"):
                md_parts.append(render_section(child, level=3))
            elif tag == "TableStruct":
                md_parts.append(render_table_struct(child))
            elif tag in _APPDX_CONFIG:
                # 附則内の附則別表・附則様式・附則付録
                md_parts.append(render_appdx(child, heading_level=3))

    # ── 別表等（本則附属・全6種） ──
    # LawBody の直下に並ぶ Appdx 系を出現順に処理する
    appdx_tags = set(_APPDX_CONFIG.keys()) - {
        "SupplProvisionAppdxTable",
        "SupplProvisionAppdxStyle",
        "SupplProvisionAppdx",
    }
    for child in law_body.get("children", []):
        if not isinstance(child, dict):
            continue
        if child.get("tag") in appdx_tags:
            md_parts.append(render_appdx(child, heading_level=2))

    return "\n\n".join(p for p in md_parts if p.strip())


# ─────────────────────────────────────────────
# ファイル I/O
# ─────────────────────────────────────────────

def convert_file(json_path: Path) -> Path:
    """1 つの JSON ファイルを変換して .md を書き出す。成功時は出力パスを返す。"""
    try:
        text = json_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except Exception as e:
        print(f"  [ERROR] JSON 読み込み失敗: {json_path.name} — {e}")
        return None

    try:
        md = json_to_markdown(data)
    except Exception as e:
        print(f"  [ERROR] 変換失敗: {json_path.name} — {e}")
        return None

    out_path = json_path.with_suffix(".md")
    out_path.write_text(md, encoding="utf-8")
    return out_path


def main():
    # このスクリプトと同じフォルダ内の .json を対象にする
    script_dir = Path(__file__).parent
    json_files = sorted(script_dir.glob("*.json"))

    if not json_files:
        print("変換対象の .json ファイルが見つかりませんでした。")
        print(f"対象フォルダ: {script_dir}")
        sys.exit(0)

    print(f"対象フォルダ: {script_dir}")
    print(f"変換対象: {len(json_files)} ファイル\n")

    ok, ng = 0, 0
    for jf in json_files:
        print(f"  変換中: {jf.name} ...", end=" ")
        out = convert_file(jf)
        if out:
            print(f"→ {out.name}")
            ok += 1
        else:
            ng += 1

    print(f"\n完了: 成功 {ok} / 失敗 {ng}")


if __name__ == "__main__":
    main()
