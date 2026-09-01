# -*- coding: utf-8 -*-
"""seed_demo_data.py - 灌入演示数据（扩充版）

运行方式:
  cd 督办系统目录
  python seed_demo_data.py

数据规模（供分页 / 筛选 / 排序 / 闭环矩阵 / 抽屉 / 消息演示）:
  - 用户 9 个（1 管理员 + 8 负责人，闭环矩阵每页 8 人 → 恰好翻 2 页）
  - 任务 45 个（任务列表每页 20 条 → 3 页），5 种状态 / 4 级优先级均有足够样本
  - 证据 16 条（text / link / file 三类型，含一个三类型齐备的任务）、阻塞 8 条（open / resolved 均有）
  - 进度日志：每条非待启动任务均有时间线记录（含完整 pending→in_progress→closed 链路）
  - 消息约 60 条（6 种类型全覆盖，约 1/3 已读）
"""

import os
import sys
from datetime import datetime, timedelta

# 确保能 import 项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import db
import models
from werkzeug.security import generate_password_hash
from state_machine import TaskStatus, change_task_status


def main():
    # 初始化数据库（如果还没有表）
    models.init_db()

    # 如果已经有管理员了，说明已经初始化过，先清空演示数据再重建
    # 注意：V2 新增的 evidence / blockers 两张表也必须一并清空，
    #       否则重复灌入时会残留旧证据 / 阻塞脏数据
    if models.has_admin():
        print('[提示] 检测到已有数据，将清空后重新灌入演示数据...')
        conn = db.get_db()
        conn.executescript("""
            DELETE FROM evidence;
            DELETE FROM blockers;
            DELETE FROM messages;
            DELETE FROM progress_logs;
            DELETE FROM tasks;
            DELETE FROM users;
            DELETE FROM system_config;
        """)
        # 重置自增序列（sqlite_sequence 存在时），保证重复灌入后 ID 稳定从 1 开始
        try:
            conn.execute("DELETE FROM sqlite_sequence")
        except Exception:
            pass  # 老库尚未产生自增记录时表不存在，忽略即可
        conn.commit()
        models.init_db()
        print('[完成] 旧数据已清空（含 evidence / blockers）')

    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    today = now.strftime('%Y-%m-%d')
    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    tomorrow = (now + timedelta(days=1)).strftime('%Y-%m-%d')
    three_days_later = (now + timedelta(days=3)).strftime('%Y-%m-%d')
    five_days_later = (now + timedelta(days=5)).strftime('%Y-%m-%d')
    twelve_days_later = (now + timedelta(days=12)).strftime('%Y-%m-%d')
    ten_days_ago = (now - timedelta(days=10)).strftime('%Y-%m-%d')
    eight_days_ago = (now - timedelta(days=8)).strftime('%Y-%m-%d')
    five_days_ago = (now - timedelta(days=5)).strftime('%Y-%m-%d')

    # --- 时间回填小工具 ---
    def due_str(offset_days):
        """相对今天的截止日期字符串（正数=未来，负数=过去）。"""
        return (now + timedelta(days=offset_days)).strftime('%Y-%m-%d')

    def ago_str(days_ago, clock='10:00:00'):
        """N 天前某时刻的完整时间字符串（用于回填 created_at / operated_at 等）。"""
        return (now - timedelta(days=days_ago)).strftime('%Y-%m-%d') + ' ' + clock

    # ============================================================
    # 1. 创建用户（1 管理员 + 8 负责人，闭环矩阵每页 8 人 → 翻 2 页）
    # ============================================================
    print('正在创建用户...')

    admin_id = models.create_user(
        username='admin',
        display_name='管理员',
        password_hash=generate_password_hash('admin123'),
        role='admin'
    )
    print(f'  管理员 admin/admin123 (ID: {admin_id})')

    zhang_id = models.create_user('zhangsan', '张三', generate_password_hash('123456'), 'owner')
    li_id = models.create_user('lisi', '李四', generate_password_hash('123456'), 'owner')
    wang_id = models.create_user('wangwu', '王五', generate_password_hash('123456'), 'owner')
    zhao_id = models.create_user('zhaoliu', '赵六', generate_password_hash('123456'), 'owner')
    sun_id = models.create_user('sunqi', '孙七', generate_password_hash('123456'), 'owner')
    zhou_id = models.create_user('zhouba', '周八', generate_password_hash('123456'), 'owner')
    wu_id = models.create_user('wujiu', '吴九', generate_password_hash('123456'), 'owner')
    zheng_id = models.create_user('zhengshi', '郑十', generate_password_hash('123456'), 'owner')
    print(f'  负责人: 张三/李四/王五/赵六/孙七/周八/吴九/郑十 (密码均为 123456)')

    # 负责人 id / 姓名速查表（新增任务数据表用，含 admin 自身）
    owner_ids = {
        'zhang': zhang_id, 'li': li_id, 'wang': wang_id, 'zhao': zhao_id,
        'sun': sun_id, 'zhou': zhou_id, 'wu': wu_id, 'zheng': zheng_id,
        'admin': admin_id,
    }
    owner_names = {
        'zhang': '张三', 'li': '李四', 'wang': '王五', 'zhao': '赵六',
        'sun': '孙七', 'zhou': '周八', 'wu': '吴九', 'zheng': '郑十',
        'admin': '管理员',
    }

    # ============================================================
    # 2. 创建基础任务（原 12 个，内容保持不变，覆盖 5 种状态）
    # ============================================================
    print('正在创建任务...')

    # --- 待启动 pending (3个) ---
    t1 = models.create_task(
        title='Q3季度总结报告撰写',
        description='汇总Q3各项目进展、完成情况、问题与风险，形成PPT汇报材料。要求：数据准确、图表清晰、结论明确。',
        created_by=admin_id, assignee=zhang_id, priority='high',
        due_date=five_days_later
    )
    # 模拟创建时间在8天前（触发第三层预警：长期待激活）
    db.execute("UPDATE tasks SET created_at = ? WHERE task_id = ?", (eight_days_ago + ' 09:00:00', t1))
    print(f'  [待启动] Q3季度总结报告 (张三，5天后截止，创建8天前→长期待激活预警)')

    t2 = models.create_task(
        title='新员工培训计划制定',
        description='制定下月新入职员工的培训计划，包含培训课程表、导师分配、考核标准。',
        created_by=admin_id, assignee=li_id, priority='medium',
        due_date=twelve_days_later
    )
    db.execute("UPDATE tasks SET created_at = ? WHERE task_id = ?", (five_days_ago + ' 10:00:00', t2))
    print(f'  [待启动] 新员工培训计划 (李四，12天后截止)')

    t3 = models.create_task(
        title='办公用品采购清单整理',
        description='统计各部门办公用品需求，整理采购清单，提交审批。',
        created_by=zhang_id, assignee=zhang_id, priority='low',
        due_date=three_days_later
    )
    print(f'  [待启动] 办公用品采购 (张三自行创建，3天后截止)')

    # --- 进行中 in_progress (3个) ---
    t4 = models.create_task(
        title='客户满意度调研方案设计',
        description='设计客户满意度调研问卷，覆盖产品体验、服务态度、响应速度三个维度，目标回收200份有效问卷。',
        created_by=admin_id, assignee=wang_id, priority='urgent',
        due_date=tomorrow  # 明天截止，即将到期预警
    )
    # 改为进行中
    change_task_status(t4, 'in_progress', admin_id, 'admin', '已安排王五负责，开始推进')
    # 回填创建时间：早于首条进度日志（5 天前启动），保证时间线顺序合理
    db.execute("UPDATE tasks SET created_at = ? WHERE task_id = ?", (ago_str(6, '10:00:00'), t4))
    print(f'  [进行中] 客户满意度调研 (王五，明天截止→即将到期预警)')

    t5 = models.create_task(
        title='服务器迁移方案评审',
        description='评审新旧服务器迁移方案，确认迁移步骤、回滚策略、停机窗口。',
        created_by=admin_id, assignee=zhang_id, priority='high',
        due_date=three_days_later
    )
    change_task_status(t5, 'in_progress', admin_id, 'admin', '方案初稿已完成，正在评审')
    # 回填创建时间：早于首条进度日志（4 天前启动）
    db.execute("UPDATE tasks SET created_at = ? WHERE task_id = ?", (ago_str(5, '09:30:00'), t5))
    print(f'  [进行中] 服务器迁移评审 (张三，3天后截止)')

    t6 = models.create_task(
        title='部门周报模板优化',
        description='优化部门周报模板，增加风险追踪、下周计划、资源需求三个板块。',
        created_by=li_id, assignee=li_id, priority='medium',
        due_date=five_days_later
    )
    change_task_status(t6, 'in_progress', li_id, 'owner', '开始修改模板结构')
    # 回填创建时间：早于首条进度日志（6 天前启动）
    db.execute("UPDATE tasks SET created_at = ? WHERE task_id = ?", (ago_str(7, '10:00:00'), t6))
    print(f'  [进行中] 周报模板优化 (李四自行创建，5天后截止)')

    # --- 已逾期 overdue (2个) ---
    t7 = models.create_task(
        title='年度预算编制与审核',
        description='编制下一年度部门预算，包含人力成本、设备采购、差旅费用、培训费用四大板块，附说明文档。',
        created_by=admin_id, assignee=zhao_id, priority='urgent',
        due_date=yesterday  # 昨天截止
    )
    change_task_status(t7, 'in_progress', admin_id, 'admin', '赵六已开始编制')
    # 回填创建时间：早于首条进度日志（3 天前登记阻塞）
    db.execute("UPDATE tasks SET created_at = ? WHERE task_id = ?", (ago_str(5, '10:00:00'), t7))
    # 手动标记为逾期
    db.execute("UPDATE tasks SET status = 'overdue', is_overdue = 1, updated_at = ? WHERE task_id = ?",
               (now_str, t7))
    models.create_progress_log(t7, None, now_str, 'in_progress', 'overdue', '系统自动标记：任务超过截止日期')
    models.create_message(zhao_id, None, 'warning_overdue',
                          f'任务「年度预算编制与审核」已逾期，请尽快处理或更新进度。', t7)
    models.create_message(admin_id, None, 'warning_overdue',
                          f'任务「年度预算编制与审核」已逾期，负责人：赵六。', t7)
    print(f'  [已逾期] 年度预算编制 (赵六，昨天截止→逾期预警)')

    t8 = models.create_task(
        title='供应商合同续签谈判',
        description='与核心供应商洽谈年度合同续签，争取价格优惠5%，锁定交付周期。',
        created_by=admin_id, assignee=wang_id, priority='high',
        due_date=five_days_ago  # 5天前截止
    )
    change_task_status(t8, 'in_progress', admin_id, 'admin', '王五已开始谈判')
    # 回填创建时间：早于首条进度日志（6 天前登记阻塞）
    db.execute("UPDATE tasks SET created_at = ? WHERE task_id = ?", (ago_str(7, '09:30:00'), t8))
    db.execute("UPDATE tasks SET status = 'overdue', is_overdue = 1, updated_at = ? WHERE task_id = ?",
               (now_str, t8))
    models.create_progress_log(t8, None, now_str, 'in_progress', 'overdue', '系统自动标记：任务超过截止日期')
    print(f'  [已逾期] 供应商合同续签 (王五，5天前截止)')

    # --- 已闭环 closed (2个) ---
    t9 = models.create_task(
        title='Q2绩效考核完成',
        description='完成Q2全员绩效考核，汇总评分结果，形成绩效报告。',
        created_by=admin_id, assignee=zhang_id, priority='high',
        due_date=five_days_ago
    )
    change_task_status(t9, 'in_progress', admin_id, 'admin', '开始收集考核数据')
    change_task_status(t9, 'closed', zhang_id, 'owner', '考核数据已收集完毕，绩效报告已提交')
    print(f'  [已闭环] Q2绩效考核 (张三，已完成)')

    t10 = models.create_task(
        title='办公网络升级实施',
        description='升级办公网络带宽，更换核心交换机，优化WiFi覆盖。',
        created_by=admin_id, assignee=zhao_id, priority='urgent',
        due_date=ten_days_ago
    )
    change_task_status(t10, 'in_progress', admin_id, 'admin', '设备已到货，开始施工')
    change_task_status(t10, 'closed', zhao_id, 'owner', '网络升级完成，测速达标，WiFi全覆盖')
    print(f'  [已闭环] 办公网络升级 (赵六，已完成)')

    # --- 已撤销 cancelled (1个) ---
    t11 = models.create_task(
        title='团建活动策划（已取消）',
        description='原计划组织部门团建活动，因预算调整取消。',
        created_by=admin_id, assignee=li_id, priority='low',
        due_date=three_days_later
    )
    change_task_status(t11, 'cancelled', admin_id, 'admin', '因预算调整，本期取消团建计划')
    print(f'  [已撤销] 团建活动策划 (李四，已取消)')

    # --- 今天截止的紧急任务 (1个) ---
    t12 = models.create_task(
        title='今日紧急：月度经营数据分析',
        description='今日下班前完成月度经营数据分析报告，提交给管理层审阅。数据包括：营收、成本、利润率、同比环比。',
        created_by=admin_id, assignee=zhang_id, priority='urgent',
        due_date=today
    )
    change_task_status(t12, 'in_progress', admin_id, 'admin', '紧急任务，今日必须完成')
    print(f'  [进行中] 今日紧急：经营数据分析 (张三，今天截止)')

    # ------------------------------------------------------------
    # 2.1 为既有任务补写 V2 字段与过程记录（progress_percent / risk_note /
    #     collaborators + 进度日志），使抽屉与列表演示有内容
    # ------------------------------------------------------------
    print('正在为既有任务补写 V2 字段与进度日志...')

    models.update_task(
        t1, risk_note='Q3各项目数据源分散，汇总口径需与PMO对齐',
        collaborators='PMO-项目专员')
    models.update_task(
        t2, risk_note='培训预算尚未最终批复，课程采购需分批进行')

    models.update_task(
        t4, progress_percent=75,
        risk_note='问卷回收进度受第三方渠道配合度影响，样本量可能不足',
        collaborators='市场部-调研执行组')
    db.execute("UPDATE progress_logs SET operated_at = ? WHERE task_id = ? AND status_to = 'in_progress'",
               (ago_str(5, '09:00:00'), t4))
    models.create_progress_log(t4, wang_id, ago_str(3, '14:00:00'), 'in_progress', 'in_progress',
                               '问卷初稿完成，已开始小范围试测')
    models.create_progress_log(t4, wang_id, ago_str(1, '10:30:00'), 'in_progress', 'in_progress',
                               '试测反馈已吸收，问卷定稿并投放')

    models.update_task(t5, progress_percent=50, collaborators='IT部-陈工')
    db.execute("UPDATE progress_logs SET operated_at = ? WHERE task_id = ? AND status_to = 'in_progress'",
               (ago_str(4, '11:00:00'), t5))
    models.create_progress_log(t5, zhang_id, ago_str(2, '16:00:00'), 'in_progress', 'in_progress',
                               '迁移方案初稿完成，等待评审会排期')

    models.update_task(t6, progress_percent=25, collaborators='各部门周报填报人')
    db.execute("UPDATE progress_logs SET operated_at = ? WHERE task_id = ? AND status_to = 'in_progress'",
               (ago_str(6, '09:30:00'), t6))
    models.create_progress_log(t6, li_id, ago_str(4, '15:00:00'), 'in_progress', 'in_progress',
                               '新模板骨架搭建完成，三个新板块占位就绪')

    models.update_task(
        t7, progress_percent=70,
        risk_note='预算编制依赖各部门报送进度，历史数据基线口径存在分歧',
        collaborators='财务部-刘会计')
    models.update_task(
        t8, progress_percent=45,
        risk_note='供应商谈判筹码有限，价格让步空间不足')

    models.update_task(t9, progress_percent=100)
    models.update_task(t10, progress_percent=100)

    models.update_task(
        t12, progress_percent=90,
        risk_note='数据源系统今晨出现短暂故障，导出延迟半天',
        collaborators='信息中心-数据组')
    db.execute("UPDATE progress_logs SET operated_at = ? WHERE task_id = ? AND status_to = 'in_progress'",
               (ago_str(0, '08:00:00'), t12))
    models.create_progress_log(t12, zhang_id, ago_str(0, '08:40:00'), 'in_progress', 'in_progress',
                               '营收与成本数据已导出，利润率测算进行中')
    print('  已为 12 个既有任务补写 V2 字段（进度/风险点/协作方）与过程记录')

    # ============================================================
    # 3. 新增任务（数据表驱动，33 个）
    # ============================================================
    # 字段说明:
    #   owner     负责人（owner_ids 键）
    #   due       截止日期偏移（天数，负数=过去）
    #   created_ago / closed_ago  创建/闭环距今天数（时间回填用）
    #   status    目标状态（pending / in_progress / overdue / closed / cancelled）
    #   progress  完成度百分比（进行中/逾期任务必填）
    #   risk / collab  V2 字段 risk_note / collaborators
    #   by_self   True=负责人自建，False=管理员指派
    #   logs      额外进度日志 [(距今天数, 备注), ...]
    #   evidence  过程证据 [(类型, 内容, 距今天数), ...]
    #   blockers  阻塞记录 [{content/days_ago/status/resolver/resolved_ago}, ...]
    print('正在创建新增任务（33 个）...')

    NEW_TASKS = [
        # ---- 张三（+2：进行中 / 已闭环）----
        {'title': '年度审计配合资料整理',
         'desc': '配合外部审计机构完成年度审计，整理合同台账、费用凭证、银行流水及往来函证，按审计清单逐项提供。',
         'owner': 'zhang', 'priority': 'high', 'due': 12, 'created_ago': 15,
         'status': 'in_progress', 'progress': 60,
         'risk': '部分费用科目的归属口径与审计师存在分歧，待财务确认后可能调整',
         'collab': '财务部-刘会计', 'by_self': False,
         'start_note': '审计机构已进场，资料整理正式启动',
         'logs': [(12, '合同台账整理完成，共归集 186 份'),
                  (5, '费用凭证核对至 9 月，发现 3 笔待补充说明')]},
        {'title': '档案室数字化改造验收',
         'desc': '完成档案数字化扫描外包项目验收，抽检扫描件清晰度、索引准确率与数据安全性。',
         'owner': 'zhang', 'priority': 'high', 'due': -6, 'created_ago': 22, 'closed_ago': 7,
         'status': 'closed', 'progress': 100,
         'risk': '外包方成果交付节奏偏慢，验收排期一压再压',
         'by_self': True,
         'start_note': '外包方提交全部成果，开始抽检',
         'close_note': '抽检 200 卷扫描件合格率 99.5%，验收通过并归档',
         'evidence': [('file', '档案数字化项目验收单.pdf', 7),
                      ('text', '抽检 200 卷扫描件，索引准确率 99.5%，验收通过', 7)]},
        # ---- 管理员（+1：待启动；使闭环矩阵凑满 9 名负责人 → 翻 2 页）----
        {'title': '督办事项月度通报编制',
         'desc': '汇总本月各督办事项的完成情况、逾期情况与预警信息，形成月度督办通报报送管理层。',
         'owner': 'admin', 'priority': 'medium', 'due': 7, 'created_ago': 9,
         'status': 'pending', 'progress': 0,
         'risk': '各负责人进度更新不及时，通报数据需逐项人工核对',
         'by_self': True},
        # ---- 李四（+2：进行中 / 已闭环）----
        {'title': '实习生转正考核方案修订',
         'desc': '修订实习生转正考核办法，明确导师评分、部门评议与转正面谈三个环节的权重与流程。',
         'owner': 'li', 'priority': 'low', 'due': 8, 'created_ago': 12,
         'status': 'in_progress', 'progress': 40,
         'risk': '各用人部门对考核权重意见不一，需多轮沟通',
         'collab': '用人部门负责人', 'by_self': True,
         'start_note': '开始修订考核办法初稿',
         'logs': [(6, '初稿完成，已发各用人部门征求意见'),
                  (2, '已收到 5 个部门反馈，两处权重建议冲突待仲裁')]},
        {'title': '社保基数调整落地办理',
         'desc': '按新社保基数完成全员缴纳基数调整，核对补退差额并通知到每位员工。',
         'owner': 'li', 'priority': 'urgent', 'due': -20, 'created_ago': 30, 'closed_ago': 21,
         'status': 'closed', 'progress': 100,
         'risk': '社保政策过渡期补退金额计算复杂，易出错',
         'collab': '财务部-刘会计', 'by_self': False,
         'start_note': '新基数文件已下发，开始系统调整',
         'close_note': '全员基数调整完成，差额补退已随当月工资发放',
         'evidence': [('link', 'http://intranet.company.local/hr/news/2025-social-base-adjust', 21),
                      ('text', '全员社保基数调整已生效，个人确认书已签收归档', 20)]},
        # ---- 王五（+4：待启动 / 进行中x2 / 已闭环）----
        {'title': '办公区绿植租摆续约比价',
         'desc': '对三家绿植租摆供应商进行报价与养护方案比价，出具续约建议报行政审批。',
         'owner': 'wang', 'priority': 'low', 'due': 55, 'created_ago': 2,
         'status': 'pending', 'progress': 0,
         'by_self': True},
        {'title': 'OA系统升级安全测评',
         'desc': '联系第三方测评机构对OA系统升级补丁开展渗透测试，输出测评报告并整改高危漏洞。',
         'owner': 'wang', 'priority': 'urgent', 'due': 4, 'created_ago': 9,
         'status': 'in_progress', 'progress': 75,
         'risk': '第三方测评排期紧张，可能影响系统上线窗口',
         'collab': 'IT部-陈工', 'by_self': False,
         'start_note': '测评机构已确认排期，测评启动',
         'logs': [(4, '第一轮渗透测试完成：高危 0、中危 2'),
                  (1, '两处中危漏洞修复完毕，等待复测')],
         'evidence': [('link', 'http://intranet.company.local/it/security/oa-pentest-q3', 4),
                      ('text', '第一轮渗透测试完成：高危 0、中危 2，已提交整改', 4),
                      ('file', 'OA系统渗透测试整改清单.xlsx', 1)]},
        {'title': '视频会议室设备更新采购',
         'desc': '更新两间视频会议室的摄像头、全向麦克风与显示屏，完成选型、比价与安装调试。',
         'owner': 'wang', 'priority': 'medium', 'due': 20, 'created_ago': 18,
         'status': 'in_progress', 'progress': 25,
         'risk': '依赖外部供应商响应速度，设备交货周期存在不确定性',
         'collab': '采购部-钱主管', 'by_self': True,
         'start_note': '完成三套设备选型方案，进入比价环节',
         'logs': [(10, '三家供应商报价已收齐，初步比价完成')],
         'evidence': [('file', '视频会议室设备报价对比表.xlsx', 10)],
         'blockers': [{'content': '首选供应商报价高于预算 15%，正在第二轮议价',
                       'days_ago': 6, 'status': 'open'}]},
        {'title': '打印外包合同到期续签',
         'desc': '完成打印设备维保与耗材外包合同的续签谈判、审批与归档。',
         'owner': 'wang', 'priority': 'low', 'due': -12, 'created_ago': 35, 'closed_ago': 13,
         'status': 'closed', 'progress': 100,
         'by_self': True,
         'start_note': '收集本年度耗材用量数据作为谈判依据',
         'close_note': '续签价格下降 3%，合同已用印归档'},
        # ---- 赵六（+5：待启动 / 进行中 / 已逾期 / 已闭环x2）----
        {'title': '办公新址装修监理巡查',
         'desc': '每周巡查新办公区装修进度与施工质量，输出巡查简报并跟踪整改项。',
         'owner': 'zhao', 'priority': 'high', 'due': 18, 'created_ago': 12,
         'status': 'pending', 'progress': 0,
         'risk': '装修公司近期人力紧张，进度存在滞后风险',
         'collab': '装修公司项目经理', 'by_self': False},
        {'title': '机房UPS电池更换实施',
         'desc': '更换机房UPS老化电池组，制定分批更换方案与断电应急预案。',
         'owner': 'zhao', 'priority': 'medium', 'due': 6, 'created_ago': 15,
         'status': 'in_progress', 'progress': 90,
         'risk': '设备到货时间受物流影响，安装窗口需与业务方协调',
         'collab': 'IT部-陈工', 'by_self': True,
         'start_note': '电池分批到货，开始第一批更换',
         'logs': [(2, '第二批 16 组到货，安装窗口定于周六凌晨')],
         'evidence': [('text', 'UPS电池已到货 32 组，安装窗口定于周六 00:00-06:00', 2)],
         'blockers': [{'content': '电池物流延误一周，到货后需重新排安装窗口',
                       'days_ago': 12, 'status': 'resolved', 'resolver': 'zhao', 'resolved_ago': 8}]},
        {'title': 'ERP系统权限年度复核',
         'desc': '复核全员ERP系统操作权限，回收离职与转岗人员冗余权限，输出权限台账。',
         'owner': 'zhao', 'priority': 'urgent', 'due': -8, 'created_ago': 20,
         'status': 'overdue', 'progress': 55,
         'risk': '权限确认依赖各业务部门配合，回收操作需逐条留痕',
         'collab': '各部门权限管理员', 'by_self': False,
         'start_note': '开始按部门拉取现有权限清单',
         'logs': [(14, '已拉取 8 个部门共 312 个账号的权限清单')],
         'blockers': [{'content': '各业务部门权限确认清单已催办两次，仍有 4 个部门未反馈',
                       'days_ago': 4, 'status': 'open'}]},
        {'title': '消防年检整改落实',
         'desc': '完成消防年检提出的 6 项整改（应急照明、疏散指示、灭火器更换等）并取得复检合格意见。',
         'owner': 'zhao', 'priority': 'high', 'due': -3, 'created_ago': 16, 'closed_ago': 2,
         'status': 'closed', 'progress': 100,
         'risk': '整改涉及施工类项目，需夜间作业窗口',
         'collab': '物业部-消防责任人', 'by_self': False,
         'start_note': '年检意见已下达，整改开始',
         'close_note': '6 项整改全部完成，复检合格意见书已归档'},
        {'title': '公司通讯录信息更新',
         'desc': '核对全员联系方式与部门归属，发布新版公司通讯录与紧急联系人清单。',
         'owner': 'zhao', 'priority': 'low', 'due': -28, 'created_ago': 42, 'closed_ago': 30,
         'status': 'closed', 'progress': 100,
         'by_self': True,
         'start_note': '开始逐部门核对人员信息',
         'close_note': '新版通讯录已发布并同步至OA门户'},
        # ---- 孙七（+6：待启动 / 进行中x2 / 已逾期 / 已闭环x2）----
        {'title': '员工图书角管理制度制定',
         'desc': '制定员工图书角借阅管理制度、书目采购清单与季度更新机制。',
         'owner': 'sun', 'priority': 'low', 'due': 30, 'created_ago': 6,
         'status': 'pending', 'progress': 0,
         'by_self': True},
        {'title': '半年度经营分析会材料编制',
         'desc': '汇总营收、成本、利润率与重点项目进展，编制半年度经营分析会汇报材料。',
         'owner': 'sun', 'priority': 'high', 'due': 10, 'created_ago': 20,
         'status': 'in_progress', 'progress': 50,
         'risk': '多部门数据汇总进度不一，口径需反复对齐',
         'collab': '各部门数据接口人', 'by_self': False,
         'start_note': '会议时间已定，材料编制启动',
         'logs': [(14, '模板与数据口径讨论定稿'),
                  (6, '营收与成本板块初稿完成'),
                  (2, '重点项目进展板块完成，待管理层预审')],
         'evidence': [('link', 'http://intranet.company.local/oa/docs/2025-h1-review-draft', 2),
                      ('file', '半年度经营分析数据底稿.xlsx', 6)]},
        {'title': '客户答谢会场地布置',
         'desc': '确认客户答谢会主会场与茶歇区布置方案、物料清单与搭建时间表。',
         'owner': 'sun', 'priority': 'medium', 'due': 2, 'created_ago': 8,
         'status': 'in_progress', 'progress': 10,
         'risk': '首选场地档期待确认，备选方案尚未锁定',
         'by_self': True,
         'start_note': '开始对接场地方与搭建商',
         'logs': [(4, '两家搭建商方案与报价已收齐')]},
        {'title': '官网内容合规自查整改',
         'desc': '对照广告法与行业宣传规范，自查整改官网宣传用语、资质证书展示与案例描述。',
         'owner': 'sun', 'priority': 'high', 'due': -22, 'created_ago': 30,
         'status': 'overdue', 'progress': 35,
         'risk': '历史页面素材源文件缺失，部分页面需重建',
         'collab': '法务部-孙律师', 'by_self': False,
         'start_note': '自查清单已下发，开始逐页核查',
         'logs': [(24, '官网 86 个页面完成首轮排查，标记待改 23 处')],
         'blockers': [{'content': '历史宣传页面素材源文件缺失，需原建站外包商配合提供',
                       'days_ago': 10, 'status': 'open'}]},
        {'title': '季度董事会会议纪要归档',
         'desc': '完成季度董事会会议纪要的整理、逐项签批与档案归档。',
         'owner': 'sun', 'priority': 'urgent', 'due': -9, 'created_ago': 22, 'closed_ago': 10,
         'status': 'closed', 'progress': 100,
         'by_self': False,
         'start_note': '会议结束，开始整理纪要',
         'close_note': '纪要完成全部签批并归档，决议事项已转入督办清单'},
        {'title': '知识产权贯标年审准备',
         'desc': '准备知识产权管理体系年审材料，配合认证机构完成现场审核。',
         'owner': 'sun', 'priority': 'high', 'due': -18, 'created_ago': 33, 'closed_ago': 19,
         'status': 'closed', 'progress': 100,
         'risk': '现场审核日期与季度结账期冲突',
         'collab': '研发部-知识产权专员', 'by_self': True,
         'start_note': '开始按年审清单准备佐证材料',
         'close_note': '现场审核通过，不符合项已全部闭环'},
        # ---- 周八（+5：待启动x2 / 已逾期 / 已撤销 / 已闭环）----
        {'title': '员工满意度调研问卷设计',
         'desc': '设计覆盖薪酬福利、职业发展、办公环境与管理沟通四个维度的满意度调研问卷。',
         'owner': 'zhou', 'priority': 'medium', 'due': 25, 'created_ago': 4,
         'status': 'pending', 'progress': 0,
         'risk': '调研维度需与管理层确认重点，避免问卷过长影响回收率',
         'by_self': False},
        {'title': '车辆保养记录台账电子化',
         'desc': '将历年公务车辆保养维修纸质记录电子化，建立可检索的车辆台账。',
         'owner': 'zhou', 'priority': 'low', 'due': 50, 'created_ago': 14,
         'status': 'pending', 'progress': 0,
         'by_self': True},
        {'title': '办公家具盘点与报废处置',
         'desc': '完成全公司办公家具盘点，报废处置超期服役家具并更新资产台账。',
         'owner': 'zhou', 'priority': 'medium', 'due': -4, 'created_ago': 17,
         'status': 'overdue', 'progress': 80,
         'risk': '报废资产处置审批环节多，历史资产卡片信息不全',
         'collab': '资产管理部-资产管理岗', 'by_self': False,
         'start_note': '盘点计划已排定，按楼层分批进行',
         'logs': [(3, '报废申请已提交，等待资产管理部门审批')],
         'blockers': [{'content': '报废资产处置审批卡在资产管理岗，流程已超一周',
                       'days_ago': 6, 'status': 'open'}]},
        {'title': '中秋游园会筹备（已取消）',
         'desc': '原计划筹备中秋游园会活动，因场地同期施工取消。',
         'owner': 'zhou', 'priority': 'low', 'due': 15, 'created_ago': 10,
         'status': 'cancelled', 'progress': 0,
         'by_self': False,
         'cancel_note': '因园区同期施工，本期活动取消'},
        {'title': '门禁一卡通系统升级验收',
         'desc': '完成门禁一卡通系统升级项目验收，核对功能点清单并办理费用结算。',
         'owner': 'zhou', 'priority': 'high', 'due': -10, 'created_ago': 26, 'closed_ago': 11,
         'status': 'closed', 'progress': 100,
         'risk': '升级切换当晚刷卡数据需人工比对，通宵值守',
         'collab': 'IT部-门禁系统厂商', 'by_self': False,
         'start_note': '升级部署完成，进入验收测试',
         'close_note': '功能点全部通过，验收报告已签批并完成结算',
         'evidence': [('file', '门禁一卡通升级验收报告.pdf', 11)]},
        # ---- 吴九（+4：进行中 / 已逾期 / 已闭环 / 已撤销）----
        {'title': '税务稽查资料准备',
         'desc': '准备税务稽查所需的近三年账簿、凭证、申报资料及关联交易说明。',
         'owner': 'wu', 'priority': 'urgent', 'due': 1, 'created_ago': 11,
         'status': 'in_progress', 'progress': 90,
         'risk': '资料量大且需三级复核，时间窗口紧张',
         'collab': '财务部-刘会计', 'by_self': False,
         'start_note': '稽查通知已收到，资料清单开始整理',
         'logs': [(3, '凭证与申报表核对完成，差异说明初稿形成')],
         'evidence': [('text', '三年账簿凭证已按清单整理完毕，存放审计资料室', 3),
                      ('file', '税务自查底稿-初稿.xlsx', 1)],
         'blockers': [{'content': '银行流水调取需走函证流程，周期较长',
                       'days_ago': 9, 'status': 'resolved', 'resolver': 'wu', 'resolved_ago': 4}]},
        {'title': 'Q4资金计划报送',
         'desc': '汇总各部门Q4资金需求与回款预测，按集团要求报送资金计划。',
         'owner': 'wu', 'priority': 'urgent', 'due': -2, 'created_ago': 14,
         'status': 'overdue', 'progress': 65,
         'risk': '各部门报送口径需统一，回款预测偏差需逐项沟通',
         'collab': '各部门资金计划填报人', 'by_self': False,
         'start_note': '资金计划模板已下发各部门',
         'logs': [(9, '已有 9 个部门报送，4 个部门催办中')]},
        {'title': '银行开户许可证年检归档',
         'desc': '完成基本户与一般户开户许可年检资料的准备、报送与归档。',
         'owner': 'wu', 'priority': 'medium', 'due': -7, 'created_ago': 19, 'closed_ago': 8,
         'status': 'closed', 'progress': 100,
         'by_self': True,
         'start_note': '年检资料清单已备齐',
         'close_note': '两户年检完成，回执已归档'},
        {'title': '财务共享中心调研立项（已取消）',
         'desc': '原计划赴外地调研财务共享中心建设经验并形成立项建议，因年度预算冻结取消。',
         'owner': 'wu', 'priority': 'medium', 'due': 8, 'created_ago': 5,
         'status': 'cancelled', 'progress': 0,
         'by_self': False,
         'cancel_note': '因年度预算冻结，调研立项取消'},
        # ---- 郑十（+4：待启动 / 进行中 / 已闭环 / 已撤销）----
        {'title': '高新技术企业资质复审准备',
         'desc': '收集知识产权、研发投入、科技人员占比等证明材料，准备高新技术企业资质复审。',
         'owner': 'zheng', 'priority': 'low', 'due': 60, 'created_ago': 1,
         'status': 'pending', 'progress': 0,
         'risk': '研发费用归集口径需与税务顾问确认',
         'by_self': True},
        {'title': 'ISO9001体系文件换版修订',
         'desc': '按新版标准要求完成质量管理体系文件的换版修订与内审员培训。',
         'owner': 'zheng', 'priority': 'medium', 'due': 15, 'created_ago': 13,
         'status': 'in_progress', 'progress': 30,
         'risk': '新版标准条款映射工作量大，涉及全部程序文件',
         'collab': '行政部-周文员', 'by_self': False,
         'start_note': '换版差距分析完成，修订工作启动',
         'logs': [(7, '质量手册修订完成，进入程序文件阶段')]},
        {'title': '安全生产标准化达标评审',
         'desc': '完成安全生产标准化三级达标评审，闭环全部评审整改项。',
         'owner': 'zheng', 'priority': 'high', 'due': -5, 'created_ago': 21, 'closed_ago': 6,
         'status': 'closed', 'progress': 100,
         'collab': '生产部-安全员', 'by_self': False,
         'start_note': '评审计划确认，材料准备启动',
         'close_note': '达标评审通过，整改项全部闭环并归档'},
        {'title': '厂区宣传视频拍摄（已取消）',
         'desc': '原计划拍摄厂区形象宣传片用于招聘与客户接待，因年度宣传预算调整取消。',
         'owner': 'zheng', 'priority': 'low', 'due': 40, 'created_ago': 7,
         'status': 'cancelled', 'progress': 0,
         'by_self': True,
         'cancel_note': '因年度宣传预算调整，拍摄计划取消'},
    ]

    STATUS_CN = {'pending': '待启动', 'in_progress': '进行中', 'overdue': '已逾期',
                 'closed': '已闭环', 'cancelled': '已撤销'}

    def due_desc(offset):
        """打印用截止日描述。"""
        if offset > 0:
            return f'{offset}天后截止'
        if offset == 0:
            return '今天截止'
        return f'超期{-offset}天'

    for spec in NEW_TASKS:
        owner_key = spec['owner']
        assignee_id = owner_ids[owner_key]
        status = spec['status']
        # 操作人：自建任务由负责人操作，管理员指派任务由管理员推动启动
        if spec.get('by_self'):
            op_id, op_role = assignee_id, 'owner'
        else:
            op_id, op_role = admin_id, 'admin'

        tid = models.create_task(
            title=spec['title'],
            description=spec['desc'],
            created_by=(assignee_id if spec.get('by_self') else admin_id),
            assignee=assignee_id,
            priority=spec['priority'],
            due_date=due_str(spec['due'])
        )
        # 记录 task_id 供消息关联使用
        spec['_id'] = tid

        # 回填创建时间（模拟任务创建于若干天前；待启动任务无后续动作）
        created_time = ago_str(spec['created_ago'], spec.get('created_clock', '09:30:00'))
        if status == 'pending':
            db.execute("UPDATE tasks SET created_at = ?, updated_at = ? WHERE task_id = ?",
                       (created_time, created_time, tid))
        else:
            db.execute("UPDATE tasks SET created_at = ? WHERE task_id = ?", (created_time, tid))

        # --- 状态流转（与 routes 层 task_new / task_status 操作路径一致）---
        start_ago = max(1, spec['created_ago'] - 2)
        if status != 'pending':
            change_task_status(tid, 'in_progress', op_id, op_role, spec.get('start_note', ''))
            # 回填启动时间，保证时间线顺序合理（创建 → 启动 → 各次进度更新）
            db.execute("UPDATE progress_logs SET operated_at = ? WHERE task_id = ? AND status_to = 'in_progress'",
                       (ago_str(start_ago, '10:30:00'), tid))

        if status == 'closed':
            # 负责人自行闭环（完整 pending → in_progress → closed 链路）
            closed_time = ago_str(spec['closed_ago'], '15:00:00')
            change_task_status(tid, 'closed', assignee_id, 'owner', spec.get('close_note', ''))
            db.execute("UPDATE progress_logs SET operated_at = ? WHERE task_id = ? AND status_to = 'closed'",
                       (closed_time, tid))
            db.execute("UPDATE tasks SET closed_at = ? WHERE task_id = ?", (closed_time, tid))
            updated_time = closed_time
        elif status == 'cancelled':
            cancel_time = ago_str(max(1, spec['created_ago'] - 1), '16:30:00')
            change_task_status(tid, 'cancelled', op_id, op_role, spec.get('cancel_note', ''))
            db.execute("UPDATE progress_logs SET operated_at = ? WHERE task_id = ? AND status_to = 'cancelled'",
                       (cancel_time, tid))
            updated_time = cancel_time
        elif status == 'overdue':
            # 沿用既有逾期模式：启动后由系统标记逾期 + 预警消息
            db.execute("UPDATE tasks SET status = 'overdue', is_overdue = 1, updated_at = ? WHERE task_id = ?",
                       (now_str, tid))
            models.create_progress_log(tid, None, now_str, 'in_progress', 'overdue',
                                       '系统自动标记：任务超过截止日期')
            models.create_message(assignee_id, None, 'warning_overdue',
                                   f'任务「{spec["title"]}」已逾期，请尽快处理或更新进度。', tid)
            models.create_message(admin_id, None, 'warning_overdue',
                                   f'任务「{spec["title"]}」已逾期，负责人：{owner_names[owner_key]}。', tid)
            updated_time = None  # 逾期标记时已回写 updated_at = now
        else:
            updated_time = ago_str(1, '17:30:00')

        # --- V2 字段补写（创建后 update_task，与 task_new 路由模式一致）---
        v2_fields = {
            'progress_percent': spec.get('progress', 0) if status != 'closed' else 100,
            'risk_note': spec.get('risk'),
            'collaborators': spec.get('collab'),
        }
        if updated_time is not None:
            v2_fields['updated_at'] = updated_time
        models.update_task(tid, **v2_fields)

        # --- 额外进度日志（进行中/逾期任务的过程记录，时间错开回填）---
        for log_days, log_note in spec.get('logs', []):
            models.create_progress_log(tid, assignee_id, ago_str(log_days, '14:30:00'),
                                       status, status, log_note)

        # --- 过程证据（text / link / file 三类型）---
        for etype, content, ev_days in spec.get('evidence', []):
            eid = models.add_evidence(tid, etype, content, assignee_id)
            db.execute("UPDATE evidence SET created_at = ? WHERE evidence_id = ?",
                       (ago_str(ev_days, '16:20:00'), eid))

        # --- 阻塞记录（open / resolved，登记与解决均留痕到时间线）---
        for b in spec.get('blockers', []):
            bid = models.add_blocker(tid, b['content'], assignee_id)
            db.execute("UPDATE blockers SET created_at = ? WHERE blocker_id = ?",
                       (ago_str(b['days_ago'], '11:00:00'), bid))
            models.create_progress_log(tid, assignee_id, ago_str(b['days_ago'], '11:00:00'),
                                       status, status, f'新增阻塞：{b["content"]}')
            if b.get('status') == 'resolved':
                resolved_time = ago_str(b['resolved_ago'], '16:00:00')
                models.resolve_blocker(bid, owner_ids[b['resolver']])
                db.execute("UPDATE blockers SET resolved_at = ? WHERE blocker_id = ?",
                           (resolved_time, bid))
                models.create_progress_log(tid, owner_ids[b['resolver']], resolved_time,
                                           status, status, f'阻塞已解决：{b["content"]}')

        print(f'  [{STATUS_CN[status]}] {spec["title"]} ({owner_names[owner_key]}，'
              f'{due_desc(spec["due"])}，创建于{spec["created_ago"]}天前)')

    # ============================================================
    # 4. 为既有任务补录证据与阻塞（t7 / t8 / t9）
    # ============================================================
    print('正在为既有任务补录证据与阻塞...')

    # t7（年度预算编制，已逾期）：未解决阻塞
    b1 = models.add_blocker(t7, '各板块预算数据口径待财务与业务部门对齐，定稿受阻', zhao_id)
    db.execute("UPDATE blockers SET created_at = ? WHERE blocker_id = ?", (ago_str(3, '14:20:00'), b1))
    models.create_progress_log(t7, zhao_id, ago_str(3, '14:20:00'), 'overdue', 'overdue',
                               '新增阻塞：各板块预算数据口径待财务与业务部门对齐，定稿受阻')

    # t8（供应商合同续签，已逾期）：已解决阻塞
    b2 = models.add_blocker(t8, '对方合同模板法务审核周期较长，续签文本迟迟未回', wang_id)
    db.execute("UPDATE blockers SET created_at = ? WHERE blocker_id = ?", (ago_str(6, '09:40:00'), b2))
    models.create_progress_log(t8, wang_id, ago_str(6, '09:40:00'), 'overdue', 'overdue',
                               '新增阻塞：对方合同模板法务审核周期较长，续签文本迟迟未回')
    models.resolve_blocker(b2, wang_id)
    db.execute("UPDATE blockers SET resolved_at = ? WHERE blocker_id = ?", (ago_str(2, '15:10:00'), b2))
    models.create_progress_log(t8, wang_id, ago_str(2, '15:10:00'), 'overdue', 'overdue',
                               '阻塞已解决：法务已加急出具审核意见，续签文本已回')

    # t9（Q2绩效考核，已闭环）：归档类证据
    e1 = models.add_evidence(t9, 'file', 'Q2绩效考核评分汇总表.xlsx', zhang_id)
    db.execute("UPDATE evidence SET created_at = ? WHERE evidence_id = ?", (ago_str(1, '16:00:00'), e1))
    e2 = models.add_evidence(t9, 'text', '绩效报告已归档至共享盘 /HR档案/2025/Q2/', zhang_id)
    db.execute("UPDATE evidence SET created_at = ? WHERE evidence_id = ?", (ago_str(1, '16:10:00'), e2))
    print('  已补录: t7 阻塞(待解决) / t8 阻塞(已解决) / t9 证据 2 条')

    # ============================================================
    # 5. 补充消息通知（让消息列表有内容，6 种类型全覆盖）
    # ============================================================
    print('正在创建消息通知...')

    # 任务指派消息
    models.create_message(zhang_id, admin_id, 'assignment',
                          '管理员给你指派了新任务「Q3季度总结报告撰写」', t1)
    models.create_message(wang_id, admin_id, 'assignment',
                          '管理员给你指派了新任务「客户满意度调研方案设计」', t4)
    models.create_message(zhao_id, admin_id, 'assignment',
                          '管理员给你指派了新任务「年度预算编制与审核」', t7)
    models.create_message(li_id, admin_id, 'assignment',
                          '管理员给你指派了新任务「新员工培训计划制定」', t2)

    # 即将到期预警
    models.create_message(wang_id, None, 'warning_due',
                          '任务「客户满意度调研方案设计」将在 1 天后到期，请及时跟进。', t4)
    models.create_message(zhang_id, None, 'warning_due',
                          '任务「今日紧急：月度经营数据分析」将在今天到期，请尽快完成。', t12)

    # 长期待激活预警
    models.create_message(zhang_id, None, 'warning_inactive',
                          '任务「Q3季度总结报告撰写」创建 8 天仍未启动，请尽快处理。', t1)
    models.create_message(admin_id, None, 'warning_inactive',
                          '任务「Q3季度总结报告撰写」创建 8 天仍未启动（负责人：张三）。', t1)

    # 管理员直接指令消息
    models.create_message(zhang_id, admin_id, 'admin_directive',
                          'Q3报告请重点关注营收增长部分的同比分析，管理层很关注这个数据。', t1)
    models.create_message(zhao_id, admin_id, 'admin_directive',
                          '预算编制请参考去年数据，人力成本板块需要细化到每个人。', t7)

    # ---- 新增任务的显式消息（逾期预警消息已在数据表循环中随状态生成）----
    task_id_by_title = {s['title']: s['_id'] for s in NEW_TASKS}

    # 任务指派消息（新增任务）
    models.create_message(wang_id, admin_id, 'assignment',
                          '管理员给你指派了新任务「OA系统升级安全测评」',
                          task_id_by_title['OA系统升级安全测评'])
    models.create_message(zhao_id, admin_id, 'assignment',
                          '管理员给你指派了新任务「ERP系统权限年度复核」',
                          task_id_by_title['ERP系统权限年度复核'])
    models.create_message(sun_id, admin_id, 'assignment',
                          '管理员给你指派了新任务「半年度经营分析会材料编制」',
                          task_id_by_title['半年度经营分析会材料编制'])
    models.create_message(wu_id, admin_id, 'assignment',
                          '管理员给你指派了新任务「税务稽查资料准备」',
                          task_id_by_title['税务稽查资料准备'])

    # 即将到期预警（新增任务）
    models.create_message(sun_id, None, 'warning_due',
                          '任务「客户答谢会场地布置」将在 2 天后到期，请及时跟进。',
                          task_id_by_title['客户答谢会场地布置'])
    models.create_message(wu_id, None, 'warning_due',
                          '任务「税务稽查资料准备」将在 1 天后到期，请及时跟进。',
                          task_id_by_title['税务稽查资料准备'])

    # 长期待激活预警（新增的长期未启动任务，负责人 + 管理员双份）
    models.create_message(zhao_id, None, 'warning_inactive',
                          '任务「办公新址装修监理巡查」创建 12 天仍未启动，请尽快处理。',
                          task_id_by_title['办公新址装修监理巡查'])
    models.create_message(admin_id, None, 'warning_inactive',
                          '任务「办公新址装修监理巡查」创建 12 天仍未启动（负责人：赵六）。',
                          task_id_by_title['办公新址装修监理巡查'])
    models.create_message(zhou_id, None, 'warning_inactive',
                          '任务「车辆保养记录台账电子化」创建 14 天仍未启动，请尽快处理。',
                          task_id_by_title['车辆保养记录台账电子化'])
    models.create_message(admin_id, None, 'warning_inactive',
                          '任务「车辆保养记录台账电子化」创建 14 天仍未启动（负责人：周八）。',
                          task_id_by_title['车辆保养记录台账电子化'])

    # 管理员直接指令消息（新增任务）
    models.create_message(sun_id, admin_id, 'admin_directive',
                          '经营分析会材料请重点关注毛利率变化与重点项目里程碑，管理层将在会上逐项过。',
                          task_id_by_title['半年度经营分析会材料编制'])
    models.create_message(zhao_id, admin_id, 'admin_directive',
                          'ERP权限复核请务必在本月内完成清单确认，集团审计将抽查。',
                          task_id_by_title['ERP系统权限年度复核'])

    # 无关联任务的系统通知（少量，验证消息可不挂任务）
    models.create_message(zhang_id, None, 'admin_directive',
                          '本周五 16:00 召开月度督办例会，请各位负责人提前准备好口头汇报要点。', None)
    models.create_message(wu_id, None, 'admin_directive',
                          '月末结账期间，各报销单请于 25 日前提交，逾期顺延至次月。', None)

    # 模拟用户已读部分消息（约 1/3 已读，其余保持未读供铃铛红点演示）
    all_msgs = db.query("SELECT message_id FROM messages ORDER BY message_id")
    read_count = 0
    for idx, msg in enumerate(all_msgs):
        if idx % 3 == 0:
            db.execute("UPDATE messages SET is_read = 1 WHERE message_id = ?",
                       (msg['message_id'],))
            read_count += 1
    print(f'  消息已读标记完成（{read_count} 已读 / {len(all_msgs) - read_count} 未读，约 1:2）')

    # ============================================================
    # 6. 统计输出（真实计数）
    # ============================================================
    print()
    print('=' * 50)
    print('演示数据灌入完成！')
    print('=' * 50)
    print()

    user_count = models.count_users()
    task_count = db.query("SELECT COUNT(*) as c FROM tasks")[0]['c']
    msg_count = db.query("SELECT COUNT(*) as c FROM messages")[0]['c']
    log_count = db.query("SELECT COUNT(*) as c FROM progress_logs")[0]['c']
    ev_count = db.query("SELECT COUNT(*) as c FROM evidence")[0]['c']
    bl_count = db.query("SELECT COUNT(*) as c FROM blockers")[0]['c']
    unread_count = db.query("SELECT COUNT(*) as c FROM messages WHERE is_read = 0")[0]['c']

    # 状态分布
    status_cn = {'pending': '待启动', 'in_progress': '进行中', 'overdue': '已逾期',
                 'closed': '已闭环', 'cancelled': '已撤销'}
    status_rows = db.query("SELECT status, COUNT(*) as c FROM tasks GROUP BY status ORDER BY status")
    # 优先级分布
    prio_cn = {'urgent': '紧急', 'high': '高', 'medium': '中', 'low': '低'}
    prio_rows = db.query("SELECT priority, COUNT(*) as c FROM tasks GROUP BY priority ORDER BY priority")
    # 负责人分布
    assignee_rows = db.query(
        "SELECT u.display_name AS name, COUNT(*) AS c FROM tasks t "
        "LEFT JOIN users u ON t.assignee = u.user_id "
        "GROUP BY t.assignee ORDER BY c DESC, u.display_name ASC")

    print(f'用户: {user_count} 个（1 管理员 + 8 负责人）')
    print(f'任务: {task_count} 个')
    for row in status_rows:
        print(f'  - {status_cn[row["status"]]}: {row["c"]} 个')
    prio_line = '、'.join(f'{prio_cn[r["priority"]]} {r["c"]} 个' for r in prio_rows)
    print(f'  优先级分布: {prio_line}')
    owner_line = '、'.join(f'{r["name"]} {r["c"]} 个' for r in assignee_rows)
    print(f'  负责人分布: {owner_line}')

    # V2 字段覆盖率
    prog_cnt = db.query("SELECT COUNT(*) as c FROM tasks WHERE progress_percent > 0")[0]['c']
    risk_cnt = db.query(
        "SELECT COUNT(*) as c FROM tasks WHERE risk_note IS NOT NULL AND risk_note != ''")[0]['c']
    collab_cnt = db.query(
        "SELECT COUNT(*) as c FROM tasks WHERE collaborators IS NOT NULL AND collaborators != ''")[0]['c']
    print(f'V2 字段: 进度已填 {prog_cnt} 个 / 风险点已填 {risk_cnt} 个 / 协作方已填 {collab_cnt} 个')

    open_bl = db.query("SELECT COUNT(*) as c FROM blockers WHERE status = 'open'")[0]['c']
    print(f'证据: {ev_count} 条（text/link/file 三类型）')
    print(f'阻塞: {bl_count} 条（待解决 {open_bl} / 已解决 {bl_count - open_bl}）')
    print(f'消息: {msg_count} 条（{msg_count - unread_count} 已读 + {unread_count} 未读，6 种类型全覆盖）')
    print(f'进度记录: {log_count} 条')
    print()
    print('登录账号：')
    print(f'  管理员: admin / admin123')
    print(f'  负责人: zhangsan / 123456')
    print(f'  负责人: lisi / 123456')
    print(f'  负责人: wangwu / 123456')
    print(f'  负责人: zhaoliu / 123456')
    print(f'  负责人: sunqi / 123456')
    print(f'  负责人: zhouba / 123456')
    print(f'  负责人: wujiu / 123456')
    print(f'  负责人: zhengshi / 123456')
    print()
    print('浏览器访问: http://127.0.0.1:5000')


if __name__ == '__main__':
    main()
