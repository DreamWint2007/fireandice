import musicanalyzer
import json
import os

def main():
    analyzer = musicanalyzer.MusicAnalyzer("audio/test1X.mp3")
    pattern = analyzer.pattern
    print(json.dumps(pattern, indent=4))
    
    # 创建输出文件夹
    output_dir = "test_music_analyze_result"
    os.makedirs(output_dir, exist_ok=True)
    
    # 写入json文件
    output_file = os.path.join(output_dir, "pattern.json")
    with open(output_file, 'w') as f:
        json.dump(pattern, f, indent=4)
    
    print(f"\n节奏数据已保存到: {output_file}")

if __name__ == "__main__":
    main()
