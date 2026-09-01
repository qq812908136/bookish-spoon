/* ============================================================
   main.js — 督办系统前端交互脚本 V2

   功能：
   1.  深色模式切换（localStorage 记忆，默认浅色）
   2.  Toast 通知（右下角滑入，3 秒消失；flash 消息自动转发）
   3.  抽屉管理器（任务详情 / Owner / 消息 共用一个抽屉容器）
   4.  抽屉内行内编辑（点字段变输入框，失焦/回车保存）
   5.  抽屉内表单 AJAX 提交（状态流转、证据、阻塞、提醒）
   6.  消息铃铛：未读红点轮询（30 秒）+ 消息抽屉
   7.  筛选表单自动提交
  8.  批量操作（全选/工具栏/校验，事件委托，兼容分页 AJAX 刷新）
  9.  任务列表分页原地刷新（AJAX 替换表格+分页，保持滚动位置）
  10. 日期输入框在 form 页通过 onfocus/onblur 切换 type 显示自定义 placeholder
   ============================================================ */

(function () {
    'use strict';

    // ============================================================
    // 1. 深色模式
    // ============================================================

    function initTheme() {
        var btn = document.getElementById('theme-toggle');
        if (!btn) return;

        function syncIcon() {
            var dark = document.documentElement.classList.contains('dark');
            var sun = btn.querySelector('.ic-sun');
            var moon = btn.querySelector('.ic-moon');
            if (sun) sun.style.display = dark ? '' : 'none';
            if (moon) moon.style.display = dark ? 'none' : '';
        }

        btn.addEventListener('click', function () {
            var dark = document.documentElement.classList.toggle('dark');
            try { localStorage.setItem('db-theme', dark ? 'dark' : 'light'); } catch (e) { }
            syncIcon();
        });

        syncIcon();
    }

    // ============================================================
    // 2. Toast 通知
    // ============================================================

    function showToast(message, type) {
        type = type || 'info';
        var container = document.getElementById('toast-container');
        if (!container) return;

        var icons = {
            success: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>',
            error: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>',
            info: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>'
        };

        var el = document.createElement('div');
        el.className = 'toast ' + type;
        el.innerHTML = '<span class="t-icon">' + (icons[type] || icons.info) + '</span><span></span>';
        el.lastChild.textContent = message;
        container.appendChild(el);

        // 下一帧触发过渡
        requestAnimationFrame(function () {
            requestAnimationFrame(function () { el.classList.add('show'); });
        });

        setTimeout(function () {
            el.classList.remove('show');
            setTimeout(function () { el.remove(); }, 350);
        }, 3000);
    }

    function initFlashToast() {
        document.querySelectorAll('.flash[data-toast]').forEach(function (el) {
            var cat = el.getAttribute('data-toast');
            var type = (cat === 'success' || cat === 'error' || cat === 'info') ? cat : 'info';
            showToast(el.getAttribute('data-toast-msg') || el.textContent, type);
        });
        // flash 3 秒淡出（兜底保留）：先平滑收起高度，内容随之下滑而非突然上跳
        document.querySelectorAll('.flash').forEach(function (el) {
            setTimeout(function () {
                el.style.transition = 'opacity 0.4s ease, max-height 0.4s ease, margin 0.4s ease, padding 0.4s ease';
                el.style.opacity = '0';
                el.style.maxHeight = el.scrollHeight + 'px';
                el.style.overflow = 'hidden';
                requestAnimationFrame(function () {
                    el.style.maxHeight = '0';
                    el.style.paddingTop = '0';
                    el.style.paddingBottom = '0';
                    el.style.marginTop = '0';
                    el.style.marginBottom = '0';
                });
                setTimeout(function () { el.remove(); }, 450);
            }, 3000);
        });
    }

    // ============================================================
    // 3. 抽屉管理器
    // ============================================================

    var drawer = {
        el: null,
        body: null,
        overlay: null,
        currentUrl: null,

        open: function (url, afterLoad) {
            this.el = this.el || document.getElementById('drawer-main');
            this.body = this.body || document.getElementById('drawer-main-body');
            this.overlay = this.overlay || document.getElementById('drawer-overlay');
            if (!this.el || !this.body) return;

            this.currentUrl = url;
            this.overlay.classList.add('open');
            this.el.classList.add('open');
            document.body.style.overflow = 'hidden';

            this.body.innerHTML = '<div style="text-align:center;padding:48px 20px;color:var(--color-text-muted);">加载中...</div>';

            var self = this;
            fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (resp) {
                    if (resp.redirected) { window.location.href = resp.url; return null; }
                    return resp.text();
                })
                .then(function (html) {
                    if (html === null) return;
                    self.body.innerHTML = html;
                    if (typeof afterLoad === 'function') afterLoad();
                })
                .catch(function () {
                    self.body.innerHTML = '<div style="text-align:center;padding:48px 20px;color:var(--color-red);">加载失败，请重试</div>';
                });
        },

        reload: function () {
            if (this.currentUrl) this.open(this.currentUrl);
        },

        close: function () {
            if (this.overlay) this.overlay.classList.remove('open');
            if (this.el) {
                this.el.classList.remove('open');
                this.body.innerHTML = '';
            }
            document.body.style.overflow = '';
            this.currentUrl = null;
        }
    };

    function initDrawerEvents() {
        // 关闭按钮（事件委托，抽屉内容动态加载）
        document.addEventListener('click', function (e) {
            if (e.target.closest('.drawer-close')) {
                drawer.close();
                return;
            }
            // 遮罩点击关闭
            if (e.target.id === 'drawer-overlay') {
                drawer.close();
                return;
            }
            // 任务行：打开任务抽屉
            // 注意：不能把 form 加入排除列表——任务列表的批量操作表单包裹了整张表格，
            // 排除 form 会导致点行永远无法打开抽屉。只排除具体交互元素。
            var row = e.target.closest('[data-drawer]');
            if (row && !e.target.closest('a, button, input, select, textarea, label')) {
                e.preventDefault();
                var url = row.getAttribute('data-drawer');
                if (url) drawer.open(url);
                return;
            }
            // 任务列表：点行跳转任务详情页（替代原抽屉行为，049）
            // 排除交互元素：复选框(input) 等，避免勾选时误跳转；标题整行可点。
            var navRow = e.target.closest('.task-row');
            if (navRow && !e.target.closest('a, button, input, select, textarea, label')) {
                var detailUrl = navRow.getAttribute('data-detail-url');
                if (detailUrl) {
                    window.location.href = detailUrl;
                    return;
                }
            }
            // 抽屉页签切换
            var tabBtn = e.target.closest('.drawer-tabs button');
            if (tabBtn) {
                var tabs = tabBtn.closest('.drawer-tabs');
                tabs.querySelectorAll('button').forEach(function (b) { b.classList.remove('active'); });
                tabBtn.classList.add('active');
                var paneId = tabBtn.getAttribute('data-tab');
                var body = tabBtn.closest('.drawer').querySelectorAll('.drawer-tab-pane');
                body.forEach(function (p) {
                    p.classList.toggle('active', p.id === paneId);
                });
                return;
            }
            // 消息抽屉：点消息 → 已读 + 打开关联任务抽屉
            var msgItem = e.target.closest('.drawer .message-item');
            if (msgItem) {
                var msgId = msgItem.getAttribute('data-message-id');
                var taskDrawerUrl = msgItem.getAttribute('data-task-drawer');
                if (msgItem.classList.contains('unread')) {
                    fetch('/messages/' + msgId + '/read', { method: 'POST' })
                        .then(function () { pollUnreadCount(); })
                        .catch(function () { });
                }
                if (taskDrawerUrl && taskDrawerUrl !== '') {
                    drawer.open(taskDrawerUrl);
                }
                return;
            }
            // 全部已读（抽屉内）
            var markAll = e.target.closest('#drawer-mark-all-read');
            if (markAll) {
                fetch('/messages/read-all', { method: 'POST' })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        showToast(data.message || '已全部标记为已读', 'success');
                        drawer.reload();
                        pollUnreadCount();
                    })
                    .catch(function () { showToast('操作失败', 'error'); });
                return;
            }
            // 推送提醒按钮
            var remind = e.target.closest('.remind-btn');
            if (remind) {
                var rUrl = remind.getAttribute('data-url');
                fetch(rUrl, { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        showToast(data.message || (data.success ? '已发送提醒' : '操作失败'), data.success ? 'success' : 'error');
                    })
                    .catch(function () { showToast('操作失败，请重试', 'error'); });
                return;
            }
            // 阻塞记录「标记解决」
            var resolveBtn = e.target.closest('.resolve-blocker-btn');
            if (resolveBtn) {
                fetch(resolveBtn.getAttribute('data-url'), {
                    method: 'POST',
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        showToast(data.message || '已标记解决', data.success ? 'success' : 'error');
                        if (data.success) drawer.reload();
                    })
                    .catch(function () { showToast('操作失败', 'error'); });
                return;
            }
            // 删除证据 / 删除阻塞（V2 批次 4，仅 admin；POST → JSON → drawer.reload + Toast）
            var delBtn = e.target.closest('.delete-evidence-btn, .delete-blocker-btn');
            if (delBtn) {
                if (!window.confirm('确定要删除吗？此操作不可撤销！')) return;
                fetch(delBtn.getAttribute('data-url'), {
                    method: 'POST',
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        showToast(data.message || (data.success ? '已删除' : '操作失败'), data.success ? 'success' : 'error');
                        if (data.success) drawer.reload();
                    })
                    .catch(function () { showToast('操作失败，请重试', 'error'); });
                return;
            }
            // Owner 抽屉中的任务行 → 任务详情抽屉
            var ownerRow = e.target.closest('.drawer .owner-task-row');
            if (ownerRow) {
                var u = ownerRow.getAttribute('data-drawer');
                if (u) drawer.open(u);
            }
        });

        // ESC 关闭
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') drawer.close();
        });

        // 铃铛 → 消息抽屉
        var bell = document.getElementById('bell-btn');
        if (bell) {
            bell.addEventListener('click', function () {
                drawer.open('/messages/drawer');
            });
        }

        // 移动端汉堡菜单
        var navToggle = document.getElementById('nav-toggle');
        var mobileNav = document.getElementById('mobile-nav');
        if (navToggle && mobileNav) {
            navToggle.addEventListener('click', function () {
                mobileNav.classList.toggle('open');
            });
            document.addEventListener('click', function (e) {
                if (!e.target.closest('#mobile-nav') && !e.target.closest('#nav-toggle')) {
                    mobileNav.classList.remove('open');
                }
            });
        }
    }

    // ============================================================
    // 4. 行内编辑（抽屉详情页签）
    // ============================================================

    function initInlineEdit() {
        document.addEventListener('click', function (e) {
            var field = e.target.closest('.inline-field.editable .field-value');
            if (!field) return;
            if (field.querySelector('input, select, textarea')) return;

            var wrap = field.closest('.inline-field');
            var fieldType = wrap.getAttribute('data-type');
            var fieldKey = wrap.getAttribute('data-field');
            var taskUrl = wrap.getAttribute('data-url');   // /tasks/<id>/field
            var optionsRaw = wrap.getAttribute('data-options');
            var current = field.getAttribute('data-raw') || field.textContent.trim();

            // 构造输入控件
            var input;
            if (fieldType === 'select' && optionsRaw) {
                input = document.createElement('select');
                JSON.parse(optionsRaw).forEach(function (opt) {
                    var o = document.createElement('option');
                    o.value = opt[0];
                    o.textContent = opt[1];
                    if (String(opt[0]) === String(current)) o.selected = true;
                    input.appendChild(o);
                });
            } else if (fieldType === 'textarea') {
                input = document.createElement('textarea');
                input.rows = 3;
                input.value = current;
            } else if (fieldType === 'number') {
                input = document.createElement('input');
                input.type = 'number';
                input.min = '0';
                input.max = '100';
                input.value = current;
            } else if (fieldType === 'date') {
                input = document.createElement('input');
                input.type = 'date';
                input.value = current;
            } else {
                input = document.createElement('input');
                input.type = 'text';
                input.value = current;
            }

            var original = input.value;
            field.innerHTML = '';
            field.appendChild(input);
            input.focus();
            if (input.select) input.select();

            function save() {
                var val = input.value;
                field.textContent = val === '' ? '—' : val;
                field.setAttribute('data-raw', val);

                if (String(val) === String(original)) return;  // 未变化

                fetch(taskUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ field: fieldKey, value: val })
                })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        if (data.success) {
                            showToast('已保存', 'success');
                            // 进度%变化时刷新进度条
                            if (fieldKey === 'progress_percent' && data.progress !== undefined) {
                                var fill = wrap.closest('.drawer').querySelector('.progress-lg .fill');
                                var pct = wrap.closest('.drawer').querySelector('.progress-lg .pct');
                                if (fill) fill.style.width = data.progress + '%';
                                if (pct) pct.textContent = data.progress + '%';
                            }
                        } else {
                            showToast(data.message || '保存失败', 'error');
                            field.textContent = original === '' ? '—' : original;
                            field.setAttribute('data-raw', original);
                        }
                    })
                    .catch(function () {
                        showToast('保存失败，请重试', 'error');
                        field.textContent = original === '' ? '—' : original;
                    });
            }

            input.addEventListener('blur', save);
            input.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' && fieldType !== 'textarea') {
                    ev.preventDefault();
                    input.blur();
                }
                if (ev.key === 'Escape') {
                    input.removeEventListener('blur', save);
                    field.textContent = original === '' ? '—' : original;
                    field.setAttribute('data-raw', original);
                }
            });
        });
    }

    // ============================================================
    // 5. 抽屉内表单 AJAX 提交（状态流转 / 证据 / 阻塞 / 进度备注）
    // ============================================================

    function initDrawerForms() {
        document.addEventListener('submit', function (e) {
            var form = e.target;
            if (!form.classList.contains('drawer-form')) return;
            e.preventDefault();

            var formData = new FormData(form);
            fetch(form.action, {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    showToast(data.message || (data.success ? '操作成功' : '操作失败'), data.success ? 'success' : 'error');
                    if (data.success) {
                        if (data.reload_page) {
                            window.location.reload();
                        } else {
                            drawer.reload();
                        }
                    }
                })
                .catch(function () { showToast('操作失败，请重试', 'error'); });
        });
    }

    // ============================================================
    // 6. 消息红点轮询（30 秒）
    // ============================================================

    var pollUnreadCount = function () {
        var badge = document.getElementById('unread-badge');
        if (!badge) return;

        fetch('/messages/unread-count')
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                var count = data.count || 0;
                if (count > 0) {
                    badge.textContent = count > 99 ? '99+' : count;
                    badge.style.display = '';
                } else {
                    badge.style.display = 'none';
                }
            })
            .catch(function () { });
    };

    function initPolling() {
        pollUnreadCount();
        setInterval(pollUnreadCount, 30000);
    }

    // ============================================================
    // 7. 筛选表单自动提交
    // ============================================================

    function initFilterAutoSubmit() {
        var filterForm = document.getElementById('filter-form');
        if (!filterForm) return;

        filterForm.querySelectorAll('select').forEach(function (sel) {
            sel.addEventListener('change', function () { filterForm.submit(); });
        });

        var searchInput = filterForm.querySelector('input[name="keyword"]');
        if (searchInput) {
            searchInput.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') filterForm.submit();
            });
        }
    }

    // ============================================================
    // 8. 批量操作（沿用 V1）
    // ============================================================

    // 批量操作状态同步（每次实时查 DOM，兼容分页 AJAX 原地刷新后重新生成的行）
    function updateBatchState() {
        var selectAll = document.getElementById('select-all');
        var toolbar = document.getElementById('batch-toolbar');
        var countEl = document.getElementById('batch-selected-count');
        var checked = document.querySelectorAll('.task-checkbox:checked');
        var total = document.querySelectorAll('.task-checkbox');
        var count = checked.length;
        if (countEl) countEl.textContent = count;
        if (toolbar) toolbar.style.display = count > 0 ? 'flex' : 'none';
        if (selectAll) {
            if (count === 0) { selectAll.checked = false; selectAll.indeterminate = false; }
            else if (count === total.length) { selectAll.checked = true; selectAll.indeterminate = false; }
            else { selectAll.checked = false; selectAll.indeterminate = true; }
        }
    }

    function initBatchOps() {
        // 复选框是分页后重新生成的，改用事件委托：
        // 点复选框 → 阻止冒泡（避免误触发行点击开抽屉）+ 更新计数
        document.addEventListener('click', function (e) {
            var cb = e.target.closest('.task-checkbox');
            if (cb) { e.stopPropagation(); updateBatchState(); return; }
            var sa = e.target.closest('#select-all');
            if (sa) {
                var boxes = document.querySelectorAll('.task-checkbox');
                boxes.forEach(function (b) { b.checked = sa.checked; });
                updateBatchState();
                return;
            }
        });

        // 复选框单元格空白区：捕获阶段拦下，避免冒泡到抽屉（抽屉监听是冒泡阶段）
        document.addEventListener('click', function (e) {
            if (e.target.closest('td.col-checkbox') && !e.target.closest('.task-checkbox')) {
                e.stopPropagation();
            }
        }, true);

        // 批量操作类型切换 → 联动显示目标状态 / 新负责人
        document.addEventListener('change', function (e) {
            var act = e.target.closest('#batch-action-select');
            if (!act) return;
            var ts = document.getElementById('batch-target-status');
            var na = document.getElementById('batch-new-assignee');
            var v = act.value;
            if (ts) {
                var s = (v === 'change_status');
                ts.style.display = s ? 'inline-block' : 'none';
                ts.disabled = !s;
                if (!s) ts.value = '';
            }
            if (na) {
                var s2 = (v === 'reassign');
                na.style.display = s2 ? 'inline-block' : 'none';
                na.disabled = !s2;
                if (!s2) na.value = '';
            }
        });

        // 批量表单提交校验（监听器挂在 form 元素上，AJAX 刷新 innerHTML 后仍然有效）
        var batchForm = document.getElementById('batch-form');
        if (batchForm) {
            batchForm.addEventListener('submit', function (e) {
                var actionSelect = document.getElementById('batch-action-select');
                var action = actionSelect ? actionSelect.value : '';
                if (!action) { e.preventDefault(); alert('请选择批量操作类型'); return; }
                var checked = document.querySelectorAll('.task-checkbox:checked');
                if (checked.length === 0) { e.preventDefault(); alert('请至少选择一条任务'); return; }
                var ts = document.getElementById('batch-target-status');
                var na = document.getElementById('batch-new-assignee');
                if (action === 'change_status' && (!ts || !ts.value)) {
                    e.preventDefault(); alert('请选择目标状态'); return;
                }
                if (action === 'reassign' && (!na || !na.value)) {
                    e.preventDefault(); alert('请选择新负责人'); return;
                }
            });
        }

        updateBatchState();
    }

    // 任务列表分页：拦截点击，原地刷新表格 + 分页，避免整页跳转导致滚动条跳到顶/底
    function initPaginationAjax() {
        // 通用分页原地刷新：拦截所有 .pagination a，fetch 新页后只替换「最近的带 id 容器」内部，
        // 滚动位置保持不变（既不回顶也不到底）。
        // 任务列表页作用域 = #batch-form（保留 form 元素与 submit 监听）；
        // 概览矩阵页作用域 = #matrix-card。
        document.addEventListener('click', function (e) {
            var link = e.target.closest('.pagination a');
            if (!link) return;
            var href = link.getAttribute('href');
            if (!href) return;
            var url;
            try { url = new URL(href, location.href); } catch (_) { return; }
            if (url.origin !== location.origin) return;

            // 找到要原地刷新的作用域容器（向上找最近的带 id 的祖先）
            var scope = link.closest('[id]');
            if (!scope) return;
            var scopeId = scope.id;

            e.preventDefault();
            fetch(url.toString(), { headers: { 'X-Requested-With': 'fetch' } })
                .then(function (r) {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.text();
                })
                .then(function (html) {
                    var doc = new DOMParser().parseFromString(html, 'text/html');
                    var newScope = doc.getElementById(scopeId);
                    var oldScope = document.getElementById(scopeId);
                    if (newScope && oldScope) {
                        oldScope.innerHTML = newScope.innerHTML;  // 只换内部，外层元素及监听保留
                        if (scopeId === 'batch-form') updateBatchState();
                    }
                    // 更新地址栏（去掉锚点），不触发滚动；replaceState 不污染历史
                    history.replaceState({}, '', url.pathname + url.search);
                })
                .catch(function () {
                    // 失败退回普通整页跳转（去掉锚点，避免又跳到顶/底）
                    location.href = href.split('#')[0];
                });
        });
    }

    // ============================================================
    // 初始化入口
    // ============================================================

    document.addEventListener('DOMContentLoaded', function () {
        initTheme();
        initFlashToast();
        initDrawerEvents();
        initInlineEdit();
        initDrawerForms();
        initPolling();
        initFilterAutoSubmit();
        initBatchOps();
        initPaginationAjax();
    });

    // 暴露给页面级脚本使用
    window.DB = {
        toast: showToast,
        drawer: drawer,
        pollUnreadCount: pollUnreadCount
    };

})();
