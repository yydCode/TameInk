import { useCallback, useEffect, useState } from "react";

/**
 * 本地存储 Hook
 * 用于作者自定义的数据（写作目标、存稿数量、今日待办等）
 * 这些数据由作者自己决定，AI 不干预
 */
export function useLocalStorage<T>(key: string, initialValue: T): [T, (value: T | ((prev: T) => T)) => void] {
  const [stored, setStored] = useState<T>(() => {
    try {
      const item = window.localStorage.getItem(key);
      return item ? (JSON.parse(item) as T) : initialValue;
    } catch {
      return initialValue;
    }
  });

  // 跨标签页同步
  useEffect(() => {
    const handler = (event: StorageEvent) => {
      if (event.key === key && event.newValue) {
        try {
          setStored(JSON.parse(event.newValue) as T);
        } catch {
          // 忽略解析失败
        }
      }
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, [key]);

  const set = useCallback(
    (value: T | ((prev: T) => T)) => {
      setStored((prev) => {
        const next = value instanceof Function ? value(prev) : value;
        try {
          window.localStorage.setItem(key, JSON.stringify(next));
        } catch {
          // 忽略写入失败（隐私模式或配额超限）
        }
        return next;
      });
    },
    [key],
  );

  return [stored, set];
}
