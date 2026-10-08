const loginForm = document.getElementById("loginForm");
loginForm.addEventListener("submit", function(e) {
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value.trim();
  const role = document.querySelector("input[name='role']:checked");

  if (!username) {
    alert("请输入账号");
    e.preventDefault();
    return;
  }
  if (!password) {
    alert("请输入密码");
    e.preventDefault();
    return;
  }
  if (!role) {
    alert("请选择登录身份：管理员 / 家属");
    e.preventDefault();
    return;
  }
});