#!/usr/bin/env python3
"""RAG 闭环测试脚本 — 对比 baseline / shallow / deep 三种模式

用法:
  python3 test_rag.py baseline  '[1,21,35,39,41]'  '苏明成人物线:从妈宝到守护者'
  python3 test_rag.py shallow   '[1,21,35,39,41]'  '苏明成人物线:从妈宝到守护者'
  python3 test_rag.py deep      null               '苏明成人物线:从妈宝到守护者'
"""
import sys, time, json
from pathlib import Path

SERVER = Path('/Users/zgl/VIBECAP/vibecut-server')
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SERVER.parent))

from lib.env import load_env
load_env()

from agents.drama_script_agents import run_drama_pipeline

PROJECT_DIR = Path('/Users/zgl/VIBECAP/都挺好')


def summarize(result, elapsed, mode, episodes):
    if not result.get('ok'):
        return {'mode': mode, 'ok': False, 'error': result.get('error'), 'elapsed': round(elapsed, 1)}
    sm = result.get('story_map', {})
    chapters = result.get('chapter_structure', {}).get('chapters', [])
    segs = result.get('segments', [])
    highlight_eps = [h.get('ep') for h in sm.get('highlight_scenes', [])]
    turning_eps = [t.get('ep') for t in sm.get('turning_points', [])]
    seg_eps = sorted(set(s.get('video_episode') for s in segs if s.get('video_episode')))
    return {
        'mode': mode,
        'ok': True,
        'elapsed': round(elapsed, 1),
        'episodes_input': episodes,
        'topic': result.get('topic'),
        'story_map': {
            'character_arcs': len(sm.get('character_arcs', [])),
            'turning_points': len(sm.get('turning_points', [])),
            'highlight_scenes': len(sm.get('highlight_scenes', [])),
            'topic_suggestions': len(sm.get('topic_suggestions', [])),
            'highlight_eps': sorted(set(highlight_eps)),
            'turning_eps': sorted(set(turning_eps)),
        },
        'chapters': len(chapters),
        'segments': len(segs),
        'total_chars': result.get('total_chars'),
        'segment_eps': seg_eps,
        'review': result.get('review'),
    }


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'baseline'
    episodes = json.loads(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != 'null' else None
    topic = sys.argv[3] if len(sys.argv) > 3 else '苏明成人物线:从妈宝到守护者'
    print(f"===== MODE={mode} episodes={episodes} topic={topic} =====", flush=True)
    t0 = time.time()
    result = run_drama_pipeline(
        project_dir=PROJECT_DIR,
        topic=topic,
        focus_episodes=episodes,
        target_duration=240,
        emit_progress=lambda step, msg, data=None: print(f"  [{step}] {msg}", flush=True),
    )
    elapsed = time.time() - t0
    out = summarize(result, elapsed, mode, episodes)
    print("RESULT_JSON=" + json.dumps(out, ensure_ascii=False), flush=True)
