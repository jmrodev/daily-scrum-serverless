"""HTML email templates (single place to change copy/branding)."""


def signup_html(name, code, activation_url):
    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
      <h2 style="color: #0284c7; margin-top: 0; font-size: 20px;">¡Bienvenido a Daily Scrum, {name}!</h2>
      <p style="color: #334155; font-size: 14px;">Para activar tu cuenta, hacé clic en el botón a continuación:</p>
      <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #0f172a; margin: 20px 0; padding: 14px; background: #f8fafc; border: 1px solid #cbd5e1; text-align: center; border-radius: 8px;">
        {code}
      </div>
      <div style="text-align: center; margin: 24px 0;">
        <a href="{activation_url}" style="background-color: #0284c7; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 14px; display: inline-block;">Activar mi Cuenta en Daily Scrum</a>
      </div>
      <p style="color: #64748b; font-size: 12px; text-align: center; margin: 8px 0;">Enlace directo: <a href="{activation_url}" style="color: #0284c7;">{activation_url}</a></p>
      <p style="color: #64748b; font-size: 12px; margin-top: 16px; margin-bottom: 0; border-top: 1px solid #f1f5f9; padding-top: 12px;">Este enlace abre directamente la pestaña de activación con tu código listo. Este código vence en 15 minutos.</p>
    </div>
    """


def invite_html(name, project, role, role_badge, code, activation_url):
    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
      <h2 style="color: #0284c7; margin-top: 0; font-size: 20px;">¡Fuiste invitado a Daily Scrum!</h2>
      <p style="color: #334155; font-size: 14px; line-height: 1.5;">
        Hola <strong>{name}</strong>, te han asignado al proyecto <strong>{project}</strong> como <strong>{role}</strong> (Rol del sistema: <em>{role_badge}</em>).
      </p>
      <p style="color: #334155; font-size: 14px;">
        Para activar tu cuenta y definir tu contraseña personal, hacé clic en el botón a continuación:
      </p>
      <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #0f172a; margin: 20px 0; padding: 14px; background: #f8fafc; border: 1px solid #cbd5e1; text-align: center; border-radius: 8px;">
        {code}
      </div>
      <div style="text-align: center; margin: 24px 0;">
        <a href="{activation_url}" style="background-color: #0284c7; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 14px; display: inline-block;">Activar mi Cuenta en Daily Scrum</a>
      </div>
      <p style="color: #64748b; font-size: 12px; text-align: center; margin: 8px 0;">Enlace directo a la app: <a href="{activation_url}" style="color: #0284c7;">{activation_url}</a></p>
      <p style="color: #64748b; font-size: 12px; margin-top: 16px; margin-bottom: 0; border-top: 1px solid #f1f5f9; padding-top: 12px;">
        El enlace te lleva directamente a la pestaña <strong>Activar Cuenta</strong> con tu correo y código precompletados. Solo tenés que ingresar tu contraseña.
      </p>
    </div>
    """


def otp_html(code, app_url):
    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
      <h2 style="color: #0284c7; margin-top: 0; font-size: 20px;">Daily Scrum & Kanban</h2>
      <p style="color: #334155; font-size: 14px;">Tu código de verificación de un solo uso para iniciar sesión es:</p>
      <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #0f172a; margin: 20px 0; padding: 14px; background: #f8fafc; border: 1px solid #cbd5e1; text-align: center; border-radius: 8px;">
        {code}
      </div>
      <div style="text-align: center; margin: 20px 0;">
        <a href="{app_url}" style="background-color: #0284c7; color: #ffffff; padding: 10px 22px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 13px; display: inline-block;">Ingresar a la Plataforma</a>
      </div>
      <p style="color: #64748b; font-size: 12px; text-align: center; margin: 8px 0;">Enlace directo: <a href="{app_url}" style="color: #0284c7;">{app_url}</a></p>
      <p style="color: #64748b; font-size: 12px; margin-top: 14px; margin-bottom: 0; border-top: 1px solid #f1f5f9; padding-top: 10px;">Válido por 10 minutos.</p>
    </div>
    """


def test_html(gmail_user, sender_name, app_url, now_iso):
    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px; border: 1px solid #10b981; border-radius: 12px; background: #ffffff;">
      <h2 style="color: #10b981; margin-top: 0; font-size: 20px;">¡Conexión Exitosa con Gmail SMTP!</h2>
      <p style="color: #334155; font-size: 14px;">Este es un correo de prueba generado desde el panel de administración de <strong>Daily Scrum & Kanban</strong>.</p>
      <p style="color: #334155; font-size: 14px;">La cuenta <code>{gmail_user}</code> y el remitente <strong>{sender_name}</strong> están funcionando a la perfección.</p>
      <div style="text-align: center; margin: 20px 0;">
        <a href="{app_url}" style="background-color: #10b981; color: #ffffff; padding: 10px 22px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 13px; display: inline-block;">Abrir Daily Scrum</a>
      </div>
      <p style="color: #64748b; font-size: 12px; text-align: center;">URL configurada: <a href="{app_url}" style="color: #0284c7;">{app_url}</a></p>
      <p style="color: #64748b; font-size: 12px; margin-top: 24px; margin-bottom: 0;">Enviado vía Gmail SMTP: {now_iso}</p>
    </div>
    """
