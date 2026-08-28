"""检查 AssetBundle 内容：对象类型 / 名称 / 尺寸（不落盘）。"""

import sys

import UnityPy


def inspect(path: str) -> None:
    env = UnityPy.load(path)
    print(f"== {path} ==")
    for obj in env.objects:
        try:
            tname = obj.type.name
            if tname == "TextAsset":
                data = obj.read()
                print(
                    f"  TextAsset path_id={obj.path_id} name={data.m_Name!r} "
                    f"size={len(data.m_Script)}"
                )
            elif tname == "Texture2D":
                tree = obj.read_typetree()
                print(
                    f"  Texture2D path_id={obj.path_id} name={tree.get('m_Name')!r} "
                    f"{tree.get('m_Width')}x{tree.get('m_Height')} "
                    f"fmt={tree.get('m_TextureFormat')} size={tree.get('m_CompleteImageSize')}"
                )
            elif tname == "MonoBehaviour":
                tree = obj.read_typetree()
                print(
                    f"  MonoBehaviour path_id={obj.path_id} name={tree.get('m_Name')!r} "
                    f"keys={list(tree)[:10]}"
                )
            else:
                tree = obj.read_typetree()
                print(f"  {tname} path_id={obj.path_id} keys={list(tree)[:8]}")
        except Exception as e:  # noqa: BLE001
            print(f"  {obj.type.name} path_id={obj.path_id} ERR: {e}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        inspect(p)

