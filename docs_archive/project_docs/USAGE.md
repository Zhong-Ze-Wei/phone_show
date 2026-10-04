# 使用说明

## 项目概述

本项目已经完成了基础架构的搭建，包括：
- ✅ 完整的数据模型定义
- ✅ 配置文件系统
- ✅ 数据收集框架
- ✅ 数据处理模块
- ✅ PDF生成功能
- ✅ 主运行脚本

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行项目

#### 查看项目状态
```bash
python run.py status
```

#### 创建示例数据（用于测试）
```bash
python run.py sample
```

#### 运行完整流程
```bash
python run.py run
```

#### 分阶段运行
```bash
# 只进行数据收集
python run.py collect --sources cmos dxomark

# 只进行数据处理
python run.py process

# 只生成PDF
python run.py generate
```

### 3. 调试模式
```bash
python run.py run --debug
```

## 项目结构

```
choise_phone/
├── README.md                    # 项目说明
├── IMPLEMENTATION_PLAN.md       # 实施计划
├── USAGE.md                     # 使用说明（本文件）
├── requirements.txt             # 依赖包列表
├── config.py                    # 配置文件
├── data_models.py               # 数据模型定义
├── data_collector.py            # 数据收集器
├── data_processor.py            # 数据处理器
├── pdf_generator.py             # PDF生成器
├── run.py                       # 主运行脚本
├── data/                        # 数据目录
│   ├── raw/                     # 原始数据
│   ├── processed/               # 处理后数据
│   └── final/                   # 最终数据
├── docs/                        # 生成的PDF文档
│   ├── by_brand/                # 按品牌分类
│   └── by_category/             # 按类别分类
└── logs/                        # 日志文件
```

## 数据源说明

### 已配置的数据源
1. **31du.cn**: 手机CMOS传感器天梯图
2. **DXOMARK.cn**: 专业手机相机评测
3. **GSMArena.com**: 国际权威手机规格数据库

### 目标手机品牌和型号
项目预设了以下中国手机品牌的2024-2025年热门机型：
- 小米：小米14系列、红米K70系列
- 华为：Mate 60系列、Pura 70系列
- 荣耀：Magic6系列、荣耀100系列
- OPPO：Find X7系列、Reno 11系列
- vivo：X100系列、iQOO 12系列
- OnePlus、Realme、iQOO等品牌

## 输出文件

### 数据文件
- `data/raw/`: 原始抓取数据（JSON格式）
- `data/processed/`: 标准化处理后的手机数据
- `data/final/`: 最终整合的数据

### PDF文档
- `docs/by_brand/`: 按品牌分类的技术报告
- `docs/by_category/`: 按类别分类的对比报告

## 配置说明

主要配置在 `config.py` 文件中：

### 数据收集配置
- `request_delay`: 请求间隔（默认2秒）
- `max_retries`: 最大重试次数（默认3次）
- `timeout`: 请求超时时间（默认30秒）

### 数据质量配置
- `min_data_quality_score`: 最低数据质量要求（默认0.6）
- `required_fields`: 必填字段列表

### PDF生成配置
- `page_size`: 页面大小（默认A4）
- `margin`: 页边距（默认20毫米）
- `max_phones_per_pdf`: 每个PDF最大手机数量（默认20个）

## 注意事项

### 使用限制
1. MCP网络搜索工具目前不可用，数据收集功能暂时无法完全使用
2. 需要根据实际网站结构调整数据解析逻辑
3. 建议先使用示例数据测试PDF生成功能

### 合规性
1. 遵守各网站的robots.txt和使用条款
2. 控制请求频率，避免对目标网站造成压力
3. 注意数据版权和合规性

### 扩展性
项目采用模块化设计，可以轻松扩展：
- 添加新的数据源
- 修改数据模型
- 自定义PDF样式
- 增加新的输出格式

## 故障排除

### 常见问题

1. **字体问题**
   - 如果PDF中中文显示不正常，请确保系统安装了中文字体
   - 可以在 `pdf_generator.py` 中修改字体路径

2. **网络请求失败**
   - 检查网络连接
   - 考虑使用代理（通过环境变量PROXY设置）

3. **权限问题**
   - 确保有写入data和docs目录的权限

4. **依赖包问题**
   - 使用虚拟环境：`python -m venv venv`
   - 激活虚拟环境后重新安装依赖

### 日志查看
项目运行时会生成详细的日志文件：
- `logs/phone_data_collection.log`

查看日志可以帮助诊断问题。

## 下一步计划

1. **完善数据收集功能**：根据实际网站结构调整解析逻辑
2. **增加更多数据源**：如其他评测网站、官方发布会资料等
3. **优化PDF样式**：改进排版和视觉效果
4. **添加数据可视化**：如传感器天梯图、评分对比图等
5. **实现自动化更新**：定期自动收集和更新数据

## 联系和支持

如有问题或建议，请通过以下方式联系：
- 查看项目日志文件了解详细错误信息
- 检查配置文件是否正确设置
- 确保网络连接和依赖包安装正确