import librosa as lbr
import numpy as np

class MusicAnalyzer:
    def __init__(self, audio_path):
        self.audio_path = audio_path
        self.pattern = self.generate_pattern()

    def generate_pattern(self, precision=2): # precision表示以多少分之一拍为最小单位，默认为1/2拍
        y, sr = lbr.load(self.audio_path) # y为音波波形，sr为采样率
        onset_env = lbr.onset.onset_strength(y=y, sr=sr) # 提取节拍强度
        tempo, beats = lbr.beat.beat_track(onset_envelope=onset_env, sr=sr)
        # print(f"Estimated tempo: {tempo:.2f} BPM")
        tempo = float(np.asarray(tempo).flat[0]) # 使用 numpy 的方法先转为数组，再取第一个元素
        sec_per_beat = 60.0 / tempo # 一拍的秒数
        onset_frames = lbr.onset.onset_detect(onset_envelope=onset_env, sr=sr, backtrack=True)
        onset_times = lbr.frames_to_time(onset_frames, sr=sr) # 将帧数转换为时间
        pattern = []
        for i in range(1, len(onset_times)):
            time_diff = float(onset_times[i]) - float(onset_times[i - 1])
            num_beats = round(time_diff / sec_per_beat * precision) / precision # 支持以1/12拍为单位
            if num_beats == 0: # 过滤掉过短的间隔（不是拍）
                continue
            angle = float(num_beats * 180) # 每拍180度
            pattern.append({
                "angle": angle,
                "event": "none"
            })
        return pattern