function isURL(str) {
  const urlRegex = /^(https?:\/\/)/i;
  return urlRegex.test(str.trim());
}

let currentAlert = null;

function showAlert(message, type = 'warning') {
  const alertContainer = document.querySelector('.alert-container');
  
  if (currentAlert) {
    currentAlert.remove();
  }

  const alertDiv = document.createElement('div');
  alertDiv.className = `alert alert-${type} alert-dismissible fade`;
  alertDiv.setAttribute('role', 'alert');
  alertDiv.innerHTML = `
    <ion-icon name="warning-outline"></ion-icon>
    ${message}
    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
  `;
  alertContainer.appendChild(alertDiv);

  setTimeout(() => {
    alertDiv.classList.add('show');
  }, 10);

  setTimeout(() => {
    alertDiv.classList.remove('show');
    setTimeout(() => {
      alertContainer.removeChild(alertDiv);
      if (currentAlert === alertDiv) {
        currentAlert = null;
      }
    }, 500);
  }, 2000);

  currentAlert = alertDiv;
}

function processSummary() {
  const content = document.getElementById('summary-content').value.trim();
  const language = document.getElementById('summary-language').value;
  const cssSelector = document.getElementById('summary-css-selector').value.trim();
  const resultDiv = document.getElementById('summary-result');
  
  if (!content) {
    showAlert('请输入内容或URL');
    return;
  }

  resultDiv.style.display = 'block';
  resultDiv.innerHTML = '<p class="text-center"><ion-icon name="hourglass-outline"></ion-icon> AI正在生成摘要，请稍候...</p>';

  setTimeout(() => {
    const summary = `这是一个由AI生成的${language === 'zh-CN' ? '简体中文' : language === 'zh-TW' ? '繁体中文' : '英文'}摘要。内容基于用户输入${isURL(content) ? 'URL' : '文本'}进行分析。${isURL(content) && cssSelector ? '使用了CSS选择器：' + cssSelector : ''}`;
    resultDiv.innerHTML = `
      <div class="copy-button" onclick="copyContent('summary-result')">
        <ion-icon name="copy-outline"></ion-icon>
        复制
      </div>
      <h2><ion-icon name="document-text-outline"></ion-icon> 文章摘要</h2><p>${summary}</p>
    `;
  }, 2000);
  
  setCookie('summary-language', language, 30);
}

function processSocial() {
  const content = document.getElementById('social-content').value.trim();
  const language = document.getElementById('social-language').value;
  const cssSelector = document.getElementById('social-css-selector').value.trim();
  const resultDiv = document.getElementById('social-result');
  
  if (!content) {
    showAlert('请输入内容或URL');
    return;
  }

  resultDiv.style.display = 'block';
  resultDiv.innerHTML = '<p class="text-center"><ion-icon name="hourglass-outline"></ion-icon> AI正在生成社交推广文案，请稍候...</p>';

  setTimeout(() => {
    const socialPost = `这是一条由AI生成的${language === 'zh-CN' ? '简体中文' : language === 'zh-TW' ? '繁体中文' : '英文'}社交推广文案。基于用户输入的${isURL(content) ? 'URL' : '文本'}内容创作。${isURL(content) && cssSelector ? '应用了CSS选择器：' + cssSelector : ''}`;
    resultDiv.innerHTML = `
      <div class="copy-button" onclick="copyContent('social-result')">
        <ion-icon name="copy-outline"></ion-icon>
        复制
      </div>
      <h2><ion-icon name="megaphone-outline"></ion-icon> 社交推广文案</h2><p>${socialPost}</p>
    `;
  }, 2000);
  
  setCookie('social-language', language, 30);
}

function processKeywords() {
  const content = document.getElementById('keywords-content').value.trim();
  const count = document.getElementById('keywords-count').value;
  const cssSelector = document.getElementById('keywords-css-selector').value.trim();
  const resultDiv = document.getElementById('keywords-result');
  
  if (!content) {
    showAlert('请输入内容或URL');
    return;
  }

  resultDiv.style.display = 'block';
  resultDiv.innerHTML = '<p class="text-center"><ion-icon name="hourglass-outline"></ion-icon> AI正在提取关键词，请稍候...</p>';

  setTimeout(() => {
    const keywords = Array.from({ length: count }, (_, i) => `关键词${i + 1}`);
    resultDiv.innerHTML = `
      <div class="copy-button" onclick="copyContent('keywords-result')">
        <ion-icon name="copy-outline"></ion-icon>
        复制
      </div>
      <h2><ion-icon name="key-outline"></ion-icon> 提取的关键词</h2><p>${keywords.join(', ')}</p>
    `;
  }, 2000);
  
  setCookie('keywords-count', count, 30);
}

function copyContent(resultId) {
  const resultDiv = document.getElementById(resultId);
  const textToCopy = resultDiv.querySelector('p').innerText;
  const tempInput = document.createElement('textarea');
  document.body.appendChild(tempInput);
  tempInput.value = textToCopy;
  tempInput.select();
  document.execCommand('copy');
  document.body.removeChild(tempInput);
  showAlert('内容已复制到剪贴板', 'success');
}

function setCookie(name, value, days) {
  const date = new Date();
  date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
  const expires = "expires=" + date.toUTCString();
  document.cookie = name + "=" + value + ";" + expires + ";path=/";
}

function getCookie(name) {
  const cookieName = name + "=";
  const decodedCookie = decodeURIComponent(document.cookie);
  const cookieArray = decodedCookie.split(';');
  for (let i = 0; i < cookieArray.length; i++) {
    let cookie = cookieArray[i];
    while (cookie.charAt(0) === ' ') {
      cookie = cookie.substring(1);
    }
    if (cookie.indexOf(cookieName) === 0) {
      return cookie.substring(cookieName.length, cookie.length);
    }
  }
  return "";
}

document.addEventListener('DOMContentLoaded', () => {
  const summaryLanguage = getCookie('summary-language');
  const socialLanguage = getCookie('social-language');
  const keywordsCount = getCookie('keywords-count');

  if (summaryLanguage) {
    document.getElementById('summary-language').value = summaryLanguage;
  }
  if (socialLanguage) {
    document.getElementById('social-language').value = socialLanguage;
  }
  if (keywordsCount) {
    document.getElementById('keywords-count').value = keywordsCount;
  }

  document.getElementById('summary-content').addEventListener('input', () => {
    syncContent('summary-content', ['social-content', 'keywords-content']);
  });

  document.getElementById('social-content').addEventListener('input', () => {
    syncContent('social-content', ['summary-content', 'keywords-content']);
  });

  document.getElementById('keywords-content').addEventListener('input', () => {
    syncContent('keywords-content', ['summary-content', 'social-content']);
  });

  document.getElementById('summary-language').addEventListener('change', () => {
    syncLanguage('summary-language', ['social-language', 'keywords-language']);
  });

  document.getElementById('social-language').addEventListener('change', () => {
    syncLanguage('social-language', ['summary-language', 'keywords-language']);
  });

  document.getElementById('keywords-language').addEventListener('change', () => {
    syncLanguage('keywords-language', ['summary-language', 'social-language']);
  });

  function syncContent(sourceId, targetIds) {
    const sourceContent = document.getElementById(sourceId).value;
    targetIds.forEach(targetId => {
      document.getElementById(targetId).value = sourceContent;
    });
  }

  function syncLanguage(sourceId, targetIds) {
    const sourceLanguage = document.getElementById(sourceId).value;
    targetIds.forEach(targetId => {
      document.getElementById(targetId).value = sourceLanguage;
    });
  }
});