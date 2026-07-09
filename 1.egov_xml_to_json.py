#!/usr/bin/env python3
"""
egov_xml_to_json.py
====================
e-gov 法令XMLを、e-gov JSONと完全一致する形式に変換するスクリプト。

【変換ルール】
  各XML要素 → {"tag": str, "attr": dict, "children": list}
  children には テキストノード(str) と 子要素(dict) が混在可能。

【ホワイトスペース方針】
  XMLインデント用の改行・半角スペース・タブ → 除去
  全角スペース(U+3000)など意味のある文字を含むテキスト → 保持

【使い方】
  # IDLEやダブルクリック起動（引数なし）
  →スクリプトと同じフォルダのXMLを全件自動変換

  # コマンドプロンプトから1ファイル変換
  python egov_xml_to_json.py input.xml

  # 出力先を指定
  python egov_xml_to_json.py input.xml -o output.json

  # 複数ファイル一括変換
  python egov_xml_to_json.py laws/*.xml -o ./json_output/

  # コンパクト出力（インデントなし）
  python egov_xml_to_json.py input.xml --compact
"""

import json
import sys
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# コア変換ロジック
# ---------------------------------------------------------------------------

def _is_meaningful_text(s):
    """
    XMLインデント用の半角空白・改行・タブだけの文字列は除去する。
    全角スペース(U+3000)など非ASCII空白を含む場合は保持する。
    """
    if s is None:
        return False
    # ASCII空白文字のみ除去して残るものがあれば意味あり
    return len(s.strip(' \t\n\r\f\v')) > 0


def _elem_to_dict(elem):
    """
    XML要素を再帰的に {"tag", "attr", "children"} 形式の辞書へ変換する。

    children の中身:
      - str  : テキストノード（elem.text / child.tail）
      - dict : 子要素（再帰）
    """
    children = []

    # 要素の先頭テキスト
    if _is_meaningful_text(elem.text):
        children.append(elem.text)

    # 子要素と、その後に続くテキスト（混在コンテンツ対応）
    for child in elem:
        children.append(_elem_to_dict(child))
        if _is_meaningful_text(child.tail):
            children.append(child.tail)

    return {
        "tag": elem.tag,
        "attr": dict(elem.attrib),
        "children": children,
    }


def xml_to_json_obj(xml_path):
    """XMLファイルを読み込み、JSON用辞書を返す。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    return _elem_to_dict(root)


# ---------------------------------------------------------------------------
# ファイルI/O ヘルパー
# ---------------------------------------------------------------------------

def convert_file(xml_path, out_path, indent=2):
    """1ファイルを変換して書き出す。"""
    obj = xml_to_json_obj(xml_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    print(f"  変換完了: {xml_path.name} -> {out_path.name}")


def resolve_output_path(xml_path, output_arg):
    """
    出力パスを決定する。
      - output_arg が None        : 入力と同じディレクトリに .json
      - output_arg がディレクトリ : そのディレクトリ内に .json
      - output_arg がファイルパス : そのまま使用
    """
    if output_arg is None:
        return xml_path.with_suffix(".json")

    out = Path(output_arg)
    if out.is_dir() or output_arg.endswith("/") or output_arg.endswith("\\"):
        return out / xml_path.with_suffix(".json").name
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="e-gov 法令XML → JSON 変換ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "inputs",
        nargs="*",          # 0個以上 → IDLEや引数なし起動に対応
        metavar="XML_FILE",
        help="変換するXMLファイル（複数指定可）。省略時はスクリプトと同じフォルダのXMLを全変換。",
    )
    parser.add_argument(
        "-o", "--output",
        metavar="OUTPUT",
        default=None,
        help="出力先ファイルまたはディレクトリ（省略時は入力と同じ場所に.json）",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="インデントなしのコンパクトなJSONを出力する",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    indent = None if args.compact else 2

    # ------------------------------------------------------------------
    # IDLE / ダブルクリック対応:
    # 引数なしで起動 → スクリプトと同じフォルダのXMLを全変換
    # ------------------------------------------------------------------
    if not args.inputs:
        script_dir = Path(__file__).parent
        xml_paths = sorted(script_dir.glob("*.xml"))
        if not xml_paths:
            print("[INFO] 同じフォルダにXMLファイルが見つかりませんでした。")
            print("       変換したいXMLをこのスクリプトと同じフォルダに置いてください。")
            input("\nEnterキーで終了...")
            return
        print(f"[INFO] 引数なし起動を検出。")
        print(f"[INFO] スクリプトと同じフォルダのXML {len(xml_paths)} 件を変換します。")
        print()
    else:
        xml_paths = [Path(p) for p in args.inputs]

    # 存在チェック
    missing = [p for p in xml_paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"[ERROR] ファイルが見つかりません: {p}")
        input("\nEnterキーで終了...")
        return

    # 複数ファイルなのにoutputがファイルパス指定の場合は警告
    if len(xml_paths) > 1 and args.output:
        out = Path(args.output)
        if not out.is_dir() and not args.output.endswith(("/", "\\")):
            print(f"[WARNING] 複数ファイル変換時はoutputをディレクトリとして扱います。")

    print(f"{len(xml_paths)} ファイルを変換します...")
    ok, ng = 0, 0
    for xml_path in xml_paths:
        out_path = resolve_output_path(xml_path, args.output)
        try:
            convert_file(xml_path, out_path, indent=indent)
            ok += 1
        except ET.ParseError as e:
            print(f"[ERROR] XMLパースエラー ({xml_path.name}): {e}")
            ng += 1
        except Exception as e:
            print(f"[ERROR] 変換失敗 ({xml_path.name}): {e}")
            ng += 1

    print()
    print(f"完了。成功: {ok} 件 / 失敗: {ng} 件")

    # IDLE・ダブルクリック起動時はウィンドウが即閉じしないよう待機
    if not args.inputs:
        input("\nEnterキーで終了...")


if __name__ == "__main__":
    main()
