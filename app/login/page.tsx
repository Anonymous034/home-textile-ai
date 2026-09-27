import DemoLoginForm from "../ui/DemoLoginForm";

export default function LoginPage() {
  return (
    <main className="demo-login-page">
      <div className="login-aurora" aria-hidden="true">
        <i className="login-aurora__glow login-aurora__glow--cyan" />
        <i className="login-aurora__glow login-aurora__glow--blue" />
        <i className="login-aurora__glow login-aurora__glow--violet" />
        <i className="login-aurora__glow login-aurora__glow--center" />
      </div>
      <DemoLoginForm />
    </main>
  );
}
