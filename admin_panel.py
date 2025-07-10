from aiohttp import web
import json
from datetime import datetime

# Безопасный импорт данных из основного бота
try:
    from bot import user_stats, blacklist, waiting_queue, active_chats, user_states, user_profiles, anonymous_names
except ImportError:
    # Если импорт не удался, создаём пустые структуры
    user_stats = {}
    blacklist = {}
    waiting_queue = []
    active_chats = {}
    user_states = {}
    user_profiles = {}
    anonymous_names = {}

from logger_config import log_system_event, log_admin_action

# HTML шаблон для админ-панели
ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Админ-панель анонимного чата</title>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .section {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }}
        .stat-card {{ background: #f5f5f5; padding: 15px; border-radius: 5px; text-align: center; }}
        .stat-number {{ font-size: 24px; font-weight: bold; color: #007bff; }}
        .table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
        .table th, .table td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        .table th {{ background-color: #f2f2f2; }}
        .refresh-btn {{ background: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }}
        .refresh-btn:hover {{ background: #0056b3; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔧 Админ-панель анонимного чата</h1>
        
        <div class="section">
            <h2>📊 Общая статистика</h2>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-number">{total_users}</div>
                    <div>Пользователей</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{active_chats_count}</div>
                    <div>Активных чатов</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{waiting_count}</div>
                    <div>В очереди</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{total_blocks}</div>
                    <div>Блокировок</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>👥 Активные чаты</h2>
            <table class="table">
                <tr>
                    <th>Пользователь 1</th>
                    <th>Пользователь 2</th>
                    <th>Ник 1</th>
                    <th>Ник 2</th>
                </tr>
                {active_chats_rows}
            </table>
        </div>
        
        <div class="section">
            <h2>⏳ Ожидающие в очереди</h2>
            <table class="table">
                <tr>
                    <th>ID</th>
                    <th>Ник</th>
                    <th>Пол</th>
                    <th>Возраст</th>
                </tr>
                {waiting_queue_rows}
            </table>
        </div>
        
        <div class="section">
            <h2>🚫 Блокировки</h2>
            <table class="table">
                <tr>
                    <th>Кто заблокировал</th>
                    <th>Кого заблокировал</th>
                    <th>До</th>
                </tr>
                {blacklist_rows}
            </table>
        </div>
        
        <div class="section">
            <h2>📈 Топ пользователей</h2>
            <table class="table">
                <tr>
                    <th>Ник</th>
                    <th>Чатов</th>
                    <th>Сообщений</th>
                    <th>Рейтинг</th>
                </tr>
                {top_users_rows}
            </table>
        </div>
        
        <button class="refresh-btn" onclick="location.reload()">🔄 Обновить</button>
    </div>
</body>
</html>
"""

async def admin_handler(request):
    """Обработчик админ-панели"""
    log_admin_action(0, "Accessed admin panel", "Web interface")
    
    # Подсчитываем статистику
    total_users = len(user_profiles)
    active_chats_count = len(active_chats) // 2  # Делим на 2, так как каждая пара записана дважды
    waiting_count = len(waiting_queue)
    total_blocks = sum(len(blocks) for blocks in blacklist.values())
    
    # Формируем строки для активных чатов
    active_chats_rows = ""
    for user_id, partner_id in active_chats.items():
        if user_id < partner_id:  # Показываем только одну сторону пары
            user_nick = anonymous_names.get(user_id, f"User-{user_id}")
            partner_nick = anonymous_names.get(partner_id, f"User-{partner_id}")
            active_chats_rows += f"<tr><td>{user_id}</td><td>{partner_id}</td><td>{user_nick}</td><td>{partner_nick}</td></tr>"
    
    # Формируем строки для очереди
    waiting_queue_rows = ""
    for user_id in waiting_queue:
        profile = user_profiles.get(user_id, {})
        nick = anonymous_names.get(user_id, f"User-{user_id}")
        gender = profile.get("gender", "Не указан")
        age = profile.get("age", "Не указан")
        waiting_queue_rows += f"<tr><td>{user_id}</td><td>{nick}</td><td>{gender}</td><td>{age}</td></tr>"
    
    # Формируем строки для блокировок
    blacklist_rows = ""
    for blocker_id, blocked_users in blacklist.items():
        for blocked_id, block_until in blocked_users.items():
            blocker_nick = anonymous_names.get(blocker_id, f"User-{blocker_id}")
            blocked_nick = anonymous_names.get(blocked_id, f"User-{blocked_id}")
            blacklist_rows += f"<tr><td>{blocker_nick}</td><td>{blocked_nick}</td><td>{block_until.strftime('%Y-%m-%d %H:%M')}</td></tr>"
    
    # Формируем топ пользователей
    top_users = sorted(user_stats.items(), key=lambda x: x[1].get("chats_count", 0), reverse=True)[:10]
    top_users_rows = ""
    for user_id, stats in top_users:
        nick = anonymous_names.get(user_id, f"User-{user_id}")
        chats = stats.get("chats_count", 0)
        messages = stats.get("messages_sent", 0)
        rating = stats.get("rating", 0)
        top_users_rows += f"<tr><td>{nick}</td><td>{chats}</td><td>{messages}</td><td>{rating}</td></tr>"
    
    # Заполняем шаблон
    html = ADMIN_HTML.format(
        total_users=total_users,
        active_chats_count=active_chats_count,
        waiting_count=waiting_count,
        total_blocks=total_blocks,
        active_chats_rows=active_chats_rows,
        waiting_queue_rows=waiting_queue_rows,
        blacklist_rows=blacklist_rows,
        top_users_rows=top_users_rows
    )
    
    return web.Response(text=html, content_type='text/html')

async def api_stats_handler(request):
    """API endpoint для получения статистики в JSON"""
    log_admin_action(0, "Accessed API stats", "JSON endpoint")
    stats = {
        "total_users": len(user_profiles),
        "active_chats": len(active_chats) // 2,
        "waiting_queue": len(waiting_queue),
        "total_blocks": sum(len(blocks) for blocks in blacklist.values()),
        "user_stats": user_stats,
        "anonymous_names": anonymous_names
    }
    return web.Response(text=json.dumps(stats, indent=2, default=str), content_type='application/json')

async def start_admin_server():
    """Запускает админ-сервер"""
    try:
        app = web.Application()
        app.router.add_get('/admin', admin_handler)
        app.router.add_get('/api/stats', api_stats_handler)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 8081)
        await site.start()
        log_system_event("Admin panel started", "http://localhost:8081/admin")
        log_system_event("API stats available", "http://localhost:8081/api/stats")
    except OSError as e:
        if "10048" in str(e):  # Порт уже занят
            log_system_event("Admin panel port 8081 is busy", "Trying alternative port")
            # Попробуем другой порт
            site = web.TCPSite(runner, 'localhost', 8082)
            await site.start()
            log_system_event("Admin panel started", "http://localhost:8082/admin")
            log_system_event("API stats available", "http://localhost:8082/api/stats")
        else:
            log_system_event("Failed to start admin panel", str(e))

if __name__ == "__main__":
    import asyncio
    asyncio.run(start_admin_server()) 