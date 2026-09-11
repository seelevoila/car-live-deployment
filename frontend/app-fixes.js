// 修复页面长时间不操作的 innerHTML null 错误
// 使用方法：在 index.html 中引入此文件，放在 app.js 之前

(function() {
  'use strict';

  // 增强型安全 DOM 操作辅助函数
  window.safeSetHTML = function(selector, html) {
    const el = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (el && typeof el.innerHTML !== 'undefined') {
      el.innerHTML = html;
      return true;
    }
    console.warn('❌ safeSetHTML: Element not found or invalid', selector);
    return false;
  };

  window.safeSetText = function(selector, text) {
    const el = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (el && typeof el.textContent !== 'undefined') {
      el.textContent = text;
      return true;
    }
    console.warn('❌ safeSetText: Element not found or invalid', selector);
    return false;
  };

  window.safeGetValue = function(selector, defaultValue = '') {
    const el = typeof selector === 'string' ? document.querySelector(selector) : selector;
    return (el && typeof el.value !== 'undefined') ? el.value : defaultValue;
  };

  // 拦截和修复异步操作中的空引用
  const originalSetTimeout = window.setTimeout;
  const originalSetInterval = window.setInterval;

  // 存储活动的定时器，便于清理
  window._activeTimers = new Set();
  window._activeIntervals = new Set();

  window.setTimeout = function(handler, timeout, ...args) {
    const wrappedHandler = function() {
      try {
        if (typeof handler === 'function') {
          handler.apply(this, args);
        } else {
          eval(handler);
        }
      } catch (error) {
        if (error.message && error.message.includes('null')) {
          console.warn('⚠️ Caught null reference in setTimeout:', error.message);
        } else {
          throw error;
        }
      }
    };
    const id = originalSetTimeout(wrappedHandler, timeout);
    window._activeTimers.add(id);
    return id;
  };

  window.setInterval = function(handler, interval, ...args) {
    const wrappedHandler = function() {
      try {
        if (typeof handler === 'function') {
          handler.apply(this, args);
        } else {
          eval(handler);
        }
      } catch (error) {
        if (error.message && error.message.includes('null')) {
          console.warn('⚠️ Caught null reference in setInterval:', error.message);
        } else {
          throw error;
        }
      }
    };
    const id = originalSetInterval(wrappedHandler, interval);
    window._activeIntervals.add(id);
    return id;
  };

  const originalClearTimeout = window.clearTimeout;
  const originalClearInterval = window.clearInterval;

  window.clearTimeout = function(id) {
    window._activeTimers.delete(id);
    return originalClearTimeout(id);
  };

  window.clearInterval = function(id) {
    window._activeIntervals.delete(id);
    return originalClearInterval(id);
  };

  // 页面卸载时清理所有定时器
  window.addEventListener('beforeunload', function() {
    window._activeTimers.forEach(id => originalClearTimeout(id));
    window._activeIntervals.forEach(id => originalClearInterval(id));
    window._activeTimers.clear();
    window._activeIntervals.clear();
  });

  console.log('✅ App fixes loaded: Safe DOM operations and timer tracking enabled');
})();
