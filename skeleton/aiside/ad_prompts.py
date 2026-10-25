"""Deterministic ad brief preparation. These endpoints never submit generation jobs."""
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

router = APIRouter()
CATALOG = Path(__file__).resolve().parents[1] / 'config' / 'ad_prompts.json'


def catalog():
    return json.loads(CATALOG.read_text(encoding='utf-8'))


class AdBrief(BaseModel):
    product: str = Field(min_length=1, max_length=120)
    requirement: str = Field(min_length=1, max_length=1800)
    facts: str = Field(default='', max_length=1800)
    audience: str = Field(default='', max_length=200)
    style: str = Field(default='', max_length=300)
    template: Literal['product_showcase', 'aida', 'fab', 'pas'] = 'product_showcase'

    @field_validator('product', 'requirement')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('请填写商品名称和广告需求')
        return value.strip()


@router.get('/api/demo/ad/catalog')
def get_catalog():
    return catalog()


@router.post('/api/demo/ad/prepare')
def prepare(body: AdBrief):
    source = catalog()
    template = next(t for t in source['templates'] if t['id'] == body.template)
    pending = ['商品参考图及外观核对', '整组关键帧一致性检查']
    if not body.facts.strip():
        pending.append('真实卖点尚未提供；当前只做外观展示，不补写功效或数据')
    if body.template == 'pas':
        pending.append('确认需求中的使用困扰与解决方式均有依据')
    if body.template == 'fab' and not body.facts.strip():
        pending.append('FAB的特征、优势与使用价值须补充确认')
    brief = body.model_dump()
    rules = '\n'.join(f'{i+1}. {rule["text"]}' for i, rule in enumerate(source['rules']))
    shared = (f'商品：{body.product}\n用户原始需求：{body.requirement}\n'
              f'用户提供、待核对的商品事实：{body.facts.strip() or "未提供，不得自行补充"}\n'
              f'目标人群：{body.audience.strip() or "未指定，不自行推断"}\n'
              f'视觉要求：{body.style.strip() or template["style"]}\n'
              '所有场景共用同一商品参考；人物出镜时另用固定人物参考。')
    scenes = []
    for index, scene in enumerate(template['scenes'], 1):
        scenes.append({'index': index, 'purpose': scene['purpose'], 'duration': 5,
                       'keyframe_instruction': scene['frame'],
                       'video_instruction': scene['motion']})
    scene_text = '\n\n'.join(
        f'场景{s["index"]}｜{s["purpose"]}｜建议{s["duration"]}秒\n'
        f'关键帧：{s["keyframe_instruction"]}\n视频动作：{s["video_instruction"]}' for s in scenes)
    prompt = f'商品广告方案草稿，等待用户确认。\n\n【共用设定】\n{shared}\n\n【场景草稿】\n{scene_text}\n\n【全片规则】\n{rules}'
    return {'version': source['version'], 'status': 'draft', 'method': 'template',
            'model_called': False, 'requires_confirmation': True, 'brief': brief,
            'template_name': template['name'], 'shared_context': shared,
            'scenes': scenes, 'pending_checks': pending, 'prompt': prompt}
