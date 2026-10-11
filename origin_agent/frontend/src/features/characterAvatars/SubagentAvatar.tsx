import { useEffect, useState } from "react";
import { useCharacterAvatarUrl } from "./characterAvatarStore";

/** 子会话面板/抽屉用的小尺寸角色头像；无 URL 或加载失败时不渲染。 */
export default function SubagentAvatar({ name }: { name: string }) {
  const avatarUrl = useCharacterAvatarUrl(name);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [avatarUrl]);

  if (!avatarUrl || failed) return null;
  return (
    <img
      className="subagent-avatar-img"
      src={avatarUrl}
      onError={() => setFailed(true)}
      alt=""
    />
  );
}
