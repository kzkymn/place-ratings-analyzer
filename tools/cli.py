#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Maps Pipeline dev / smoke-test CLI

The product entry point is the MCP server (src/server.py). This CLI is a dev
utility invoked directly from the terminal to exercise or debug the pipeline
on its own.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import GoogleMapsPipeline

def main():
    parser = argparse.ArgumentParser(
        description='Google Maps 一気通貫分析パイプライン（開発・疎通確認用）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 特定のスポット検索 (ピンポイントな検索で高速な結果が期待できます)
  python tools/cli.py "東京タワー"
  python tools/cli.py "渋谷スクランブル交差点" --max-results 1

  # フリーフォーマット検索 (自然言語での多様なクエリに対応します)
  python tools/cli.py "新宿の美味しいラーメン屋" --concurrency 8 --output results.json
  python tools/cli.py "京都の観光スポット" --simple
        """
    )
    
    parser.add_argument('query', help='検索クエリ (例: "東京タワー")')
    parser.add_argument('--max-results', type=int, default=20, help='最大結果数 (default: 20)')
    parser.add_argument('--concurrency', type=int, default=8, help='同時実行数 (default: 8)')
    parser.add_argument('--output', help='結果出力ファイル (JSON形式)')
    parser.add_argument('--keep-csv', help='中間CSVファイルを保存するパス')
    parser.add_argument('--scraper-path', help='Go scraperバイナリのパス')
    parser.add_argument('--simple', action='store_true', help='詳細情報（営業時間）を除外 ※口コミ本文は現在取得不可')
    
    args = parser.parse_args()
    
    try:
        pipeline = GoogleMapsPipeline(scraper_path=args.scraper_path)

        # Step 1: extract data
        csv_file = pipeline.extract_places(
            query=args.query,
            max_results=args.max_results,
            output_file=args.keep_csv,
            concurrency=args.concurrency
        )
        
        try:
            # Step 2: analyze
            results = pipeline.analyze_results(csv_file, detailed_info=not args.simple)

            # Step 3: console output
            print("\n" + "="*60)
            print("📋 詳細分析結果")
            print("="*60)
            pipeline._print_console_output(results)
            
            # JSON output
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
                print(f"\n💾 結果をJSONで保存: {args.output}")
        
            print(f"\n🎉 パイプライン完了! 総計{results['total_places']}件の店舗を分析しました")

        finally:
            # Remove the temp file
            if args.keep_csv is None and csv_file.startswith('/tmp/'):
                try:
                    os.unlink(csv_file)
                except:
                    pass

    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
