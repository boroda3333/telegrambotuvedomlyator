def should_respond_to_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Определяет, нужно ли обрабатывать сообщение для непрочитанных"""
    if not update or not update.message:
        return False
    
    # Игнорируем сообщения от самого бота
    if update.message.from_user.id == context.bot.id:
        return False
        
    # Игнорируем менеджеров
    username = update.message.from_user.username
    if is_manager(update.message.from_user.id, username):
        return False
        
    # Игнорируем служебные сообщения
    if (update.message.new_chat_members or 
        update.message.left_chat_member or 
        update.message.pinned_message or
        update.edited_message):
        return False
        
    # Игнорируем пустые сообщения
    if update.message.text and len(update.message.text.strip()) < 1:
        return False
        
    # ИГНОРИРУЕМ ВСЕ КОМАНДЫ (кастомные и обычные) - их обрабатывают CommandHandler
    if update.message.text and update.message.text.startswith('/'):
        return False
        
    # ВСЕ остальные сообщения обрабатываем (ТОЛЬКО обычный текст, фото, документы и т.д.)
    return True

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает сообщения в группах - ТОЛЬКО ОБЫЧНЫЕ СООБЩЕНИЯ"""
    if not update or not update.message:
        return
        
    logger.info(f"📨 [GROUP] Сообщение в группе: {update.message.chat.title}")
    logger.info(f"📨 [GROUP] От: {update.message.from_user.id} ({update.message.from_user.username})")
    logger.info(f"📨 [GROUP] Текст: {update.message.text[:100] if update.message.text else '[без текста]'}")
    
    # ЕСЛИ ЭТО КОМАНДА - ПОЛНОСТЬЮ ПРОПУСКАЕМ ЭТОТ ОБРАБОТЧИК
    if update.message.text and update.message.text.startswith('/'):
        logger.info(f"🔍 [GROUP] Пропускаем команду в MessageHandler: {update.message.text}")
        return
    
    # Проверяем, нужно ли обрабатывать это сообщение для непрочитанных
    if not should_respond_to_message(update, context):
        logger.info("❌ [GROUP] Сообщение не требует обработки (менеджер/служебное/команда)")
        return
    
    # Обрабатываем ТОЛЬКО обычные сообщения
    if not is_working_hours():
        # Нерабочее время - отправляем автоответ
        chat_id = update.message.chat.id
        replied_key = f'chat_{chat_id}'
        if not flags_manager.has_replied(replied_key):
            logger.info(f"🕐 [GROUP] Нерабочее время, отправляем автоответ")
            await update.message.reply_text(AUTO_REPLY_MESSAGE)
            flags_manager.set_replied(replied_key)
            logger.info(f"✅ Автоответ отправлен в чат {chat_id}")
    else:
        # Рабочее время - добавляем в непрочитанные
        chat_id = update.message.chat.id
        replied_key = f'chat_{chat_id}'
        
        # Сбрасываем флаг автоответа если был
        if flags_manager.has_replied(replied_key):
            flags_manager.clear_replied(replied_key)
        
        chat_title = update.message.chat.title
        username = update.message.from_user.username
        first_name = update.message.from_user.first_name
        message_text = update.message.text or update.message.caption or "[Сообщение без текста]"
        
        logger.info(f"✅ [GROUP] Добавляем в непрочитанные: {message_text[:50]}...")
        
        pending_messages_manager.add_message(
            chat_id=update.message.chat.id,
            user_id=update.message.from_user.id,
            message_text=message_text,
            message_id=update.message.message_id,
            chat_title=chat_title,
            username=username,
            first_name=first_name
        )
        logger.info(f"✅ Добавлено в непрочитанные: чат '{chat_title}', пользователь {first_name or username or update.message.from_user.id}")
        
        # НЕ отправляем уведомление автоматически - только по расписанию
        logger.info("📝 Новое сообщение добавлено, уведомление будет отправлено по расписанию")

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает личные сообщения - ТОЛЬКО ОБЫЧНЫЕ СООБЩЕНИЯ"""
    if not update or not update.message:
        return
        
    logger.info(f"📨 [PRIVATE] Личное сообщение от {update.message.from_user.id}")
    logger.info(f"📨 [PRIVATE] Текст: {update.message.text[:100] if update.message.text else '[без текста]'}")
    
    # ЕСЛИ ЭТО КОМАНДА - ПОЛНОСТЬЮ ПРОПУСКАЕМ ЭТОТ ОБРАБОТЧИК
    if update.message.text and update.message.text.startswith('/'):
        logger.info(f"🔍 [PRIVATE] Пропускаем команду в MessageHandler: {update.message.text}")
        return
    
    # Проверяем, нужно ли обрабатывать это сообщение для непрочитанных
    if not should_respond_to_message(update, context):
        logger.info("❌ [PRIVATE] Сообщение не требует обработки (менеджер/служебное/команда)")
        return
    
    # Обрабатываем ТОЛЬКО обычные сообщения
    if not is_working_hours():
        # Нерабочее время - отправляем автоответ
        user_id = update.message.from_user.id
        replied_key = f'user_{user_id}'
        if not flags_manager.has_replied(replied_key):
            logger.info(f"🕐 [PRIVATE] Нерабочее время, отправляем автоответ")
            await update.message.reply_text(AUTO_REPLY_MESSAGE)
            flags_manager.set_replied(replied_key)
            logger.info(f"✅ Автоответ отправлен пользователю {user_id}")
    else:
        # Рабочее время - добавляем в непрочитанные
        user_id = update.message.from_user.id
        replied_key = f'user_{user_id}'
        
        # Сбрасываем флаг автоответа если был
        if flags_manager.has_replied(replied_key):
            flags_manager.clear_replied(replied_key)
        
        username = update.message.from_user.username
        first_name = update.message.from_user.first_name
        message_text = update.message.text or update.message.caption or "[Сообщение без текста]"
        
        logger.info(f"✅ [PRIVATE] Добавляем в непрочитанные: {message_text[:50]}...")
        
        pending_messages_manager.add_message(
            chat_id=update.message.chat.id,
            user_id=update.message.from_user.id,
            message_text=message_text,
            message_id=update.message.message_id,
            username=username,
            first_name=first_name
        )
        logger.info(f"✅ Добавлено в непрочитанные: пользователь {first_name or username or user_id}")
        
        # НЕ отправляем уведомление автоматически - только по расписанию
        logger.info("📝 Новое сообщение добавлено, уведомление будет отправлено по расписанию")
