# 代码由 Siddharth Ahuja 创建：www.github.com/ahujasid © 2025

import re
import bpy
import mathutils
import json
import threading
import socket
import time
import requests
import tempfile
import traceback
import os
import shutil
import zipfile
from bpy.props import IntProperty, BoolProperty
import io
from datetime import datetime
import hashlib, hmac, base64
import os.path as osp
from contextlib import redirect_stdout, suppress

bl_info = {
    "name": "Blender MCP（简体中文）",
    "author": "BlenderMCP",
    "version": (1, 2),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > BlenderMCP",
    "description": "通过 MCP 将 Blender 连接到 Claude",
    "category": "Interface",
}

RODIN_FREE_TRIAL_KEY = "vibecoding"

# 按 Poly Haven API 要求添加 User-Agent
REQ_HEADERS = requests.utils.default_headers()
REQ_HEADERS.update({"User-Agent": "blender-mcp"})

def get_blendermcp_addon_preferences(context=None):
    """获取插件首选项对象（如果可用）。"""
    if context is None:
        context = bpy.context
    addon = context.preferences.addons.get(__name__)
    return addon.preferences if addon else None

class BlenderMCPServer:
    def __init__(self, host='localhost', port=9876):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.server_thread = None

    def _get_config_value(self, scene_attr, pref_attr=None, env_var=None):
        """按顺序读取配置：插件首选项 -> 场景 -> 环境变量。"""
        prefs = get_blendermcp_addon_preferences()
        if prefs and pref_attr:
            pref_value = getattr(prefs, pref_attr, "")
            if pref_value:
                return pref_value

        scene_value = getattr(bpy.context.scene, scene_attr, "")
        if scene_value:
            return scene_value

        if env_var:
            env_value = os.getenv(env_var, "")
            if env_value:
                return env_value
        return ""

    def _get_hyper3d_api_key(self):
        # 让免费试用按钮临时覆盖持久化密钥
        # 而不覆盖用户保存的私有密钥。
        scene_value = getattr(bpy.context.scene, "blendermcp_hyper3d_api_key", "")
        if scene_value == RODIN_FREE_TRIAL_KEY:
            return scene_value
        return self._get_config_value(
            "blendermcp_hyper3d_api_key",
            "hyper3d_api_key",
            "BLENDERMCP_HYPER3D_API_KEY",
        )

    def _get_sketchfab_api_key(self):
        return self._get_config_value(
            "blendermcp_sketchfab_api_key",
            "sketchfab_api_key",
            "BLENDERMCP_SKETCHFAB_API_KEY",
        )

    def _get_hunyuan3d_secret_id(self):
        return self._get_config_value(
            "blendermcp_hunyuan3d_secret_id",
            "hunyuan3d_secret_id",
            "BLENDERMCP_HUNYUAN3D_SECRET_ID",
        )

    def _get_hunyuan3d_secret_key(self):
        return self._get_config_value(
            "blendermcp_hunyuan3d_secret_key",
            "hunyuan3d_secret_key",
            "BLENDERMCP_HUNYUAN3D_SECRET_KEY",
        )

    def _get_hunyuan3d_api_url(self):
        return self._get_config_value(
            "blendermcp_hunyuan3d_api_url",
            "hunyuan3d_api_url",
            "BLENDERMCP_HUNYUAN3D_API_URL",
        ) or "http://localhost:8081"

    def start(self):
        if bpy.app.background:
            print("BlenderMCP: 无法在后台模式 (blender -b) 下启动服务器 - 命令将无法执行\n"
                  "BlenderMCP: 请使用 GUI 运行 Blender，或使用虚拟显示：xvfb-run -a blender")
            return

        if self.running:
            print("服务器已在运行中")
            return

        self.running = True

        try:
            # 创建套接字
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)

            # 启动服务器线程
            self.server_thread = threading.Thread(target=self._server_loop)
            self.server_thread.daemon = True
            self.server_thread.start()

            print(f"BlenderMCP 服务器已在 {self.host}:{self.port} 上启动")
        except Exception as e:
            print(f"启动服务器失败：{str(e)}")
            self.stop()

    def stop(self):
        self.running = False

        # 关闭套接字
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None

        # 等待线程完成
        if self.server_thread:
            try:
                if self.server_thread.is_alive():
                    self.server_thread.join(timeout=1.0)
            except:
                pass
            self.server_thread = None

        print("BlenderMCP 服务器已停止")

    def _server_loop(self):
        """在独立线程中的主服务器循环"""
        print("服务器线程已启动")
        self.socket.settimeout(1.0)  # 超时以允许停止

        while self.running:
            try:
                # 接受新连接
                try:
                    client, address = self.socket.accept()
                    print(f"已连接到客户端：{address}")

                    # 在独立线程中处理客户端
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                except socket.timeout:
                    # 仅检查运行状态
                    continue
                except Exception as e:
                    print(f"接受连接时出错：{str(e)}")
                    time.sleep(0.5)
            except Exception as e:
                print(f"服务器循环中出错：{str(e)}")
                if not self.running:
                    break
                time.sleep(0.5)

        print("服务器线程已停止")

    def _handle_client(self, client):
        """处理已连接的客户端"""
        print("客户端处理器已启动")
        client.settimeout(None)  # 无超时
        buffer = b''

        try:
            while self.running:
                # 接收数据
                try:
                    data = client.recv(8192)
                    if not data:
                        print("客户端已断开连接")
                        break

                    buffer += data
                    try:
                        # 尝试解析命令
                        command = json.loads(buffer.decode('utf-8'))
                        buffer = b''

                        # 在 Blender 主线程中执行命令
                        def execute_wrapper():
                            try:
                                response = self.execute_command(command)
                                response_json = json.dumps(response)
                                try:
                                    client.sendall(response_json.encode('utf-8'))
                                except:
                                    print("发送响应失败 - 客户端已断开连接")
                            except Exception as e:
                                print(f"执行命令时出错：{str(e)}")
                                traceback.print_exc()
                                try:
                                    error_response = {
                                        "status": "error",
                                        "message": str(e)
                                    }
                                    client.sendall(json.dumps(error_response).encode('utf-8'))
                                except:
                                    pass
                            return None

                        # 在主线程中调度执行
                        bpy.app.timers.register(execute_wrapper, first_interval=0.0)
                    except json.JSONDecodeError:
                        # 数据不完整，等待更多数据
                        pass
                except Exception as e:
                    print(f"接收数据时出错：{str(e)}")
                    break
        except Exception as e:
            print(f"客户端处理器中出错：{str(e)}")
        finally:
            try:
                client.close()
            except:
                pass
            print("客户端处理器已停止")

    def execute_command(self, command):
        """在 Blender 主线程中执行命令"""
        try:
            return self._execute_command_internal(command)

        except Exception as e:
            print(f"执行命令时出错：{str(e)}")
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def _execute_command_internal(self, command):
        """使用适当上下文的内部命令执行"""
        cmd_type = command.get("type")
        params = command.get("params", {})

        # 添加检查 PolyHaven 状态的处理器
        if cmd_type == "get_polyhaven_status":
            return {"status": "success", "result": self.get_polyhaven_status()}

        # 始终可用的基础处理器
        handlers = {
            "get_scene_info": self.get_scene_info,
            "get_object_info": self.get_object_info,
            "get_viewport_screenshot": self.get_viewport_screenshot,
            "execute_code": self.execute_code,
            "get_telemetry_consent": self.get_telemetry_consent,
            "get_polyhaven_status": self.get_polyhaven_status,
            "get_hyper3d_status": self.get_hyper3d_status,
            "get_sketchfab_status": self.get_sketchfab_status,
            "get_hunyuan3d_status": self.get_hunyuan3d_status,
        }

        # 仅在启用时添加 Polyhaven 处理器
        if bpy.context.scene.blendermcp_use_polyhaven:
            polyhaven_handlers = {
                "get_polyhaven_categories": self.get_polyhaven_categories,
                "search_polyhaven_assets": self.search_polyhaven_assets,
                "download_polyhaven_asset": self.download_polyhaven_asset,
                "set_texture": self.set_texture,
            }
            handlers.update(polyhaven_handlers)

        # 仅在启用时添加 Hyper3d 处理器
        if bpy.context.scene.blendermcp_use_hyper3d:
            polyhaven_handlers = {
                "create_rodin_job": self.create_rodin_job,
                "poll_rodin_job_status": self.poll_rodin_job_status,
                "import_generated_asset": self.import_generated_asset,
            }
            handlers.update(polyhaven_handlers)

        # 仅在启用时添加 Sketchfab 处理器
        if bpy.context.scene.blendermcp_use_sketchfab:
            sketchfab_handlers = {
                "search_sketchfab_models": self.search_sketchfab_models,
                "get_sketchfab_model_preview": self.get_sketchfab_model_preview,
                "download_sketchfab_model": self.download_sketchfab_model,
            }
            handlers.update(sketchfab_handlers)
        
        # 仅在启用时添加 Hunyuan3d 处理器
        if bpy.context.scene.blendermcp_use_hunyuan3d:
            hunyuan_handlers = {
                "create_hunyuan_job": self.create_hunyuan_job,
                "poll_hunyuan_job_status": self.poll_hunyuan_job_status,
                "import_generated_asset_hunyuan": self.import_generated_asset_hunyuan
            }
            handlers.update(hunyuan_handlers)

        handler = handlers.get(cmd_type)
        if handler:
            try:
                print(f"正在执行处理器：{cmd_type}")
                result = handler(**params)
                print(f"处理器执行完成")
                return {"status": "success", "result": result}
            except Exception as e:
                print(f"处理器中出错：{str(e)}")
                traceback.print_exc()
                return {"status": "error", "message": str(e)}
        else:
            return {"status": "error", "message": f"未知命令类型：{cmd_type}"}



    def get_scene_info(self):
        """获取当前 Blender 场景的信息"""
        try:
            print("正在获取场景信息...")
            # 简化场景信息以减少数据大小
            scene_info = {
                "name": bpy.context.scene.name,
                "object_count": len(bpy.context.scene.objects),
                "objects": [],
                "materials_count": len(bpy.data.materials),
            }

            # 收集最少的对象信息（限制为前 10 个对象）
            for i, obj in enumerate(bpy.context.scene.objects):
                if i >= 10:  # 从 20 减少到 10
                    break

                obj_info = {
                    "name": obj.name,
                    "type": obj.type,
                    # 仅包含基本位置数据
                    "location": [round(float(obj.location.x), 2),
                                round(float(obj.location.y), 2),
                                round(float(obj.location.z), 2)],
                }
                scene_info["objects"].append(obj_info)

            print(f"场景信息已收集：{len(scene_info['objects'])} 个对象")
            return scene_info
        except Exception as e:
            print(f"获取场景信息时出错：{str(e)}")
            traceback.print_exc()
            return {"error": str(e)}

    @staticmethod
    def _get_aabb(obj):
        """ 返回对象的世界空间轴对齐包围盒（AABB）。 """
        if obj.type != 'MESH':
            raise TypeError("对象必须是网格")

        # 获取局部空间中的包围盒角点
        local_bbox_corners = [mathutils.Vector(corner) for corner in obj.bound_box]

        # 转换为世界坐标
        world_bbox_corners = [obj.matrix_world @ corner for corner in local_bbox_corners]

        # 计算轴对齐的最小/最大坐标
        min_corner = mathutils.Vector(map(min, zip(*world_bbox_corners)))
        max_corner = mathutils.Vector(map(max, zip(*world_bbox_corners)))

        return [
            [*min_corner], [*max_corner]
        ]



    def get_object_info(self, name):
        """获取特定对象的详细信息"""
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"未找到对象：{name}")

        # 基本对象信息
        obj_info = {
            "name": obj.name,
            "type": obj.type,
            "location": [obj.location.x, obj.location.y, obj.location.z],
            "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
            "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            "visible": obj.visible_get(),
            "materials": [],
        }

        if obj.type == "MESH":
            bounding_box = self._get_aabb(obj)
            obj_info["world_bounding_box"] = bounding_box

        # 添加材质槽
        for slot in obj.material_slots:
            if slot.material:
                obj_info["materials"].append(slot.material.name)

        # 如果适用则添加网格数据
        if obj.type == 'MESH' and obj.data:
            mesh = obj.data
            obj_info["mesh"] = {
                "vertices": len(mesh.vertices),
                "edges": len(mesh.edges),
                "polygons": len(mesh.polygons),
            }

        return obj_info

    def get_viewport_screenshot(self, max_size=800, filepath=None, format="png"):
        """
        捕获当前 3D 视口的截图并保存到指定路径。

        参数：
        - max_size: 图片最大尺寸（像素）
        - filepath: 截图文件保存路径
        - format: 图片格式（png, jpg 等）

        返回成功/错误状态
        """
        # screen.screenshot_area 捕获操作系统窗口帧缓冲区，
        # 当 Blender 窗口未在前台合成时（通过 MCP 以无头模式驱动
        # Blender 时的正常情况），该缓冲区全黑。改用
        # gpu.types.GPUOffScreen.draw_view3d 渲染视口，它独立于
        # 窗口合成状态，如果离屏渲染不可用（例如没有 GPU 上下文），
        # 则回退到窗口捕获。响应报告哪个路径生成了图像。
        try:
            if not filepath:
                return {"error": "未提供文件路径"}

            area = region = space = None
            for a in bpy.context.screen.areas:
                if a.type == 'VIEW_3D':
                    area = a
                    space = a.spaces.active
                    region = next((r for r in a.regions if r.type == 'WINDOW'), None)
                    break

            if not area or region is None or space is None:
                return {"error": "未找到 3D 视口"}

            method = "offscreen"
            try:
                import gpu
                import numpy as np

                r3d = space.region_3d
                src_w, src_h = region.width, region.height
                if max(src_w, src_h) > max_size:
                    s = max_size / max(src_w, src_h)
                    width, height = max(1, int(src_w * s)), max(1, int(src_h * s))
                else:
                    width, height = src_w, src_h

                offscreen = gpu.types.GPUOffScreen(width, height)
                try:
                    offscreen.draw_view3d(
                        bpy.context.scene, bpy.context.view_layer, space, region,
                        r3d.view_matrix, r3d.window_matrix, do_color_management=True,
                    )
                    buf = offscreen.texture_color.read()
                finally:
                    offscreen.free()

                buf.dimensions = width * height * 4
                pixels = np.asarray(buf, dtype=np.float32) / 255.0  # GPU 缓冲区为 0..255

                image = bpy.data.images.new("mcp_viewport", width, height, alpha=True)
                image.pixels.foreach_set(pixels.ravel())
                image.filepath_raw = filepath
                image.file_format = format.upper()
                image.save()
                bpy.data.images.remove(image)

            except Exception as offscreen_err:
                print(f"[BlenderMCP] 离屏捕获失败 ({offscreen_err}); "
                      "回退到窗口捕获", flush=True)
                method = "window_grab"
                with bpy.context.temp_override(area=area):
                    bpy.ops.screen.screenshot_area(filepath=filepath)
                img = bpy.data.images.load(filepath)
                width, height = img.size
                if max(width, height) > max_size:
                    s = max_size / max(width, height)
                    width, height = int(width * s), int(height * s)
                    img.scale(width, height)
                    img.file_format = format.upper()
                    img.save()
                bpy.data.images.remove(img)

            return {
                "success": True,
                "width": width,
                "height": height,
                "filepath": filepath,
                "method": method,
            }

        except Exception as e:
            return {"error": str(e)}

    def execute_code(self, code):
        """执行任意 Blender Python 代码"""
        # 这很强大但有潜在危险 - 请谨慎使用
        try:
            # 创建用于执行的本地命名空间
            namespace = {"bpy": bpy}

            # 在执行期间捕获标准输出，并作为结果返回
            capture_buffer = io.StringIO()
            with redirect_stdout(capture_buffer):
                exec(code, namespace)

            captured_output = capture_buffer.getvalue()
            return {"executed": True, "result": captured_output}
        except Exception as e:
            raise Exception(f"代码执行错误：{str(e)}")



    def get_polyhaven_categories(self, asset_type):
        """从 Polyhaven 获取特定资产类型的分类"""
        try:
            if asset_type not in ["hdris", "textures", "models", "all"]:
                return {"error": f"无效的资产类型：{asset_type}。必须是以下之一：hdris, textures, models, all"}

            response = requests.get(f"https://api.polyhaven.com/categories/{asset_type}", headers=REQ_HEADERS)
            if response.status_code == 200:
                return {"categories": response.json()}
            else:
                return {"error": f"API 请求失败，状态码：{response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def search_polyhaven_assets(self, asset_type=None, categories=None):
        """从 Polyhaven 搜索资产（可选过滤）"""
        try:
            url = "https://api.polyhaven.com/assets"
            params = {}

            if asset_type and asset_type != "all":
                if asset_type not in ["hdris", "textures", "models"]:
                    return {"error": f"无效的资产类型：{asset_type}。必须是以下之一：hdris, textures, models, all"}
                params["type"] = asset_type

            if categories:
                params["categories"] = categories

            response = requests.get(url, params=params, headers=REQ_HEADERS)
            if response.status_code == 200:
                # 限制响应大小以避免使 Blender 过载
                assets = response.json()
                # 仅返回前 20 个资产以保持响应大小可控
                limited_assets = {}
                for i, (key, value) in enumerate(assets.items()):
                    if i >= 20:  # 限制为 20 个资产
                        break
                    limited_assets[key] = value

                return {"assets": limited_assets, "total_count": len(assets), "returned_count": len(limited_assets)}
            else:
                return {"error": f"API 请求失败，状态码：{response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def download_polyhaven_asset(self, asset_id, asset_type, resolution="1k", file_format=None):
        try:
            # 首先获取文件信息
            files_response = requests.get(f"https://api.polyhaven.com/files/{asset_id}", headers=REQ_HEADERS)
            if files_response.status_code != 200:
                return {"error": f"获取资产文件失败：{files_response.status_code}"}

            files_data = files_response.json()

            # 处理不同的资产类型
            if asset_type == "hdris":
                # 对于 HDRI，下载 .hdr 或 .exr 文件
                if not file_format:
                    file_format = "hdr"  # HDRI 的默认格式

                if "hdri" in files_data and resolution in files_data["hdri"] and file_format in files_data["hdri"][resolution]:
                    file_info = files_data["hdri"][resolution][file_format]
                    file_url = file_info["url"]

                    # 对于 HDRI，我们需要先保存到临时文件
                    # 因为 Blender 无法直接从内存正确加载 HDR 数据
                    with tempfile.NamedTemporaryFile(suffix=f".{file_format}", delete=False) as tmp_file:
                        # 下载文件
                        response = requests.get(file_url, headers=REQ_HEADERS)
                        if response.status_code != 200:
                            return {"error": f"Failed to download HDRI: {response.status_code}"}

                        tmp_file.write(response.content)
                        tmp_path = tmp_file.name

                    try:
                        # 如果没有世界环境则创建一个新的
                        if not bpy.data.worlds:
                            bpy.data.worlds.new("World")

                        world = bpy.data.worlds[0]
                        world.use_nodes = True
                        node_tree = world.node_tree

                        # 清除现有节点
                        for node in node_tree.nodes:
                            node_tree.nodes.remove(node)

                        # 创建节点
                        tex_coord = node_tree.nodes.new(type='ShaderNodeTexCoord')
                        tex_coord.location = (-800, 0)

                        mapping = node_tree.nodes.new(type='ShaderNodeMapping')
                        mapping.location = (-600, 0)

                        # 从临时文件加载图像
                        env_tex = node_tree.nodes.new(type='ShaderNodeTexEnvironment')
                        env_tex.location = (-400, 0)
                        env_tex.image = bpy.data.images.load(tmp_path)

                        # 使用在所有 Blender 版本中都存在的色彩空间
                        if file_format.lower() == 'exr':
                            # 尝试为 EXR 文件使用 Linear 色彩空间
                            try:
                                env_tex.image.colorspace_settings.name = 'Linear'
                            except:
                                # 如果 Linear 不可用则回退到 Non-Color
                                env_tex.image.colorspace_settings.name = 'Non-Color'
                        else:  # hdr
                            # 对于 HDR 文件，按顺序尝试以下选项
                            for color_space in ['Linear', 'Linear Rec.709', 'Non-Color']:
                                try:
                                    env_tex.image.colorspace_settings.name = color_space
                                    break  # 成功设置色彩空间后停止
                                except:
                                    continue

                        background = node_tree.nodes.new(type='ShaderNodeBackground')
                        background.location = (-200, 0)

                        output = node_tree.nodes.new(type='ShaderNodeOutputWorld')
                        output.location = (0, 0)

                        # 连接节点
                        node_tree.links.new(tex_coord.outputs['Generated'], mapping.inputs['Vector'])
                        node_tree.links.new(mapping.outputs['Vector'], env_tex.inputs['Vector'])
                        node_tree.links.new(env_tex.outputs['Color'], background.inputs['Color'])
                        node_tree.links.new(background.outputs['Background'], output.inputs['Surface'])

                        # 设置为活动世界环境
                        bpy.context.scene.world = world

                        # 清理临时文件
                        try:
                            tempfile._cleanup()  # 这将清理所有临时文件
                        except:
                            pass

                        return {
                            "success": True,
                            "message": f"HDRI {asset_id} imported successfully",
                            "image_name": env_tex.image.name
                        }
                    except Exception as e:
                        return {"error": f"Failed to set up HDRI in Blender: {str(e)}"}
                else:
                    return {"error": f"Requested resolution or format not available for this HDRI"}

            elif asset_type == "textures":
                if not file_format:
                    file_format = "jpg"  # 纹理的默认格式

                downloaded_maps = {}

                try:
                    for map_type in files_data:
                        if map_type not in ["blend", "gltf"]:  # 跳过非纹理文件
                            if resolution in files_data[map_type] and file_format in files_data[map_type][resolution]:
                                file_info = files_data[map_type][resolution][file_format]
                                file_url = file_info["url"]

                                # 使用与 HDRI 相同的 NamedTemporaryFile 方式
                                with tempfile.NamedTemporaryFile(suffix=f".{file_format}", delete=False) as tmp_file:
                                    # 下载文件
                                    response = requests.get(file_url, headers=REQ_HEADERS)
                                    if response.status_code == 200:
                                        tmp_file.write(response.content)
                                        tmp_path = tmp_file.name

                                        # 从临时文件加载图像
                                        image = bpy.data.images.load(tmp_path)
                                        image.name = f"{asset_id}_{map_type}.{file_format}"

                                        # 将图像打包到 .blend 文件中
                                        image.pack()

                                        # 根据贴图类型设置色彩空间
                                        if map_type in ['color', 'diffuse', 'albedo']:
                                            try:
                                                image.colorspace_settings.name = 'sRGB'
                                            except:
                                                pass
                                        else:
                                            try:
                                                image.colorspace_settings.name = 'Non-Color'
                                            except:
                                                pass

                                        downloaded_maps[map_type] = image

                                        # 清理临时文件
                                        try:
                                            os.unlink(tmp_path)
                                        except:
                                            pass

                    if not downloaded_maps:
                        return {"error": f"No texture maps found for the requested resolution and format"}

                    # 使用下载的纹理创建新材质
                    mat = bpy.data.materials.new(name=asset_id)
                    mat.use_nodes = True
                    nodes = mat.node_tree.nodes
                    links = mat.node_tree.links

                    # 清除默认节点
                    for node in nodes:
                        nodes.remove(node)

                    # 创建输出节点
                    output = nodes.new(type='ShaderNodeOutputMaterial')
                    output.location = (300, 0)

                    # 创建 Principled BSDF 节点
                    principled = nodes.new(type='ShaderNodeBsdfPrincipled')
                    principled.location = (0, 0)
                    links.new(principled.outputs[0], output.inputs[0])

                    # 根据可用贴图添加纹理节点
                    tex_coord = nodes.new(type='ShaderNodeTexCoord')
                    tex_coord.location = (-800, 0)

                    mapping = nodes.new(type='ShaderNodeMapping')
                    mapping.location = (-600, 0)
                    mapping.vector_type = 'TEXTURE'  # 从默认的 'POINT' 改为 'TEXTURE'
                    links.new(tex_coord.outputs['UV'], mapping.inputs['Vector'])

                    # 纹理节点的位置偏移
                    x_pos = -400
                    y_pos = 300

                    # 连接不同的纹理贴图
                    for map_type, image in downloaded_maps.items():
                        tex_node = nodes.new(type='ShaderNodeTexImage')
                        tex_node.location = (x_pos, y_pos)
                        tex_node.image = image

                        # 根据贴图类型设置色彩空间
                        if map_type.lower() in ['color', 'diffuse', 'albedo']:
                            try:
                                tex_node.image.colorspace_settings.name = 'sRGB'
                            except:
                                pass  # 如果 sRGB 不可用则使用默认值
                        else:
                            try:
                                tex_node.image.colorspace_settings.name = 'Non-Color'
                            except:
                                pass  # 如果 Non-Color 不可用则使用默认值

                        links.new(mapping.outputs['Vector'], tex_node.inputs['Vector'])

                        # 连接到 Principled BSDF 的相应输入
                        if map_type.lower() in ['color', 'diffuse', 'albedo']:
                            links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
                        elif map_type.lower() in ['roughness', 'rough']:
                            links.new(tex_node.outputs['Color'], principled.inputs['Roughness'])
                        elif map_type.lower() in ['metallic', 'metalness', 'metal']:
                            links.new(tex_node.outputs['Color'], principled.inputs['Metallic'])
                        elif map_type.lower() in ['normal', 'nor']:
                            # 添加法线贴图节点
                            normal_map = nodes.new(type='ShaderNodeNormalMap')
                            normal_map.location = (x_pos + 200, y_pos)
                            links.new(tex_node.outputs['Color'], normal_map.inputs['Color'])
                            links.new(normal_map.outputs['Normal'], principled.inputs['Normal'])
                        elif map_type in ['displacement', 'disp', 'height']:
                            # 添加置换节点
                            disp_node = nodes.new(type='ShaderNodeDisplacement')
                            disp_node.location = (x_pos + 200, y_pos - 200)
                            links.new(tex_node.outputs['Color'], disp_node.inputs['Height'])
                            links.new(disp_node.outputs['Displacement'], output.inputs['Displacement'])

                        y_pos -= 250

                    return {
                        "success": True,
                        "message": f"Texture {asset_id} imported as material",
                        "material": mat.name,
                        "maps": list(downloaded_maps.keys())
                    }

                except Exception as e:
                    return {"error": f"Failed to process textures: {str(e)}"}

            elif asset_type == "models":
                # 对于模型，优先使用 glTF 格式（如果可用）
                if not file_format:
                    file_format = "gltf"  # 模型的默认格式

                if file_format in files_data and resolution in files_data[file_format]:
                    file_info = files_data[file_format][resolution][file_format]
                    file_url = file_info["url"]

                    # 创建临时目录存储模型及其依赖文件
                    temp_dir = tempfile.mkdtemp()
                    main_file_path = ""

                    try:
                        # 下载主模型文件
                        main_file_name = file_url.split("/")[-1]
                        main_file_path = os.path.join(temp_dir, main_file_name)

                        response = requests.get(file_url, headers=REQ_HEADERS)
                        if response.status_code != 200:
                            return {"error": f"Failed to download model: {response.status_code}"}

                        with open(main_file_path, "wb") as f:
                            f.write(response.content)

                        # 检查并下载包含的文件
                        if "include" in file_info and file_info["include"]:
                            for include_path, include_info in file_info["include"].items():
                                # 获取包含文件的 URL - 这是修复方案
                                include_url = include_info["url"]

                                # 验证 include_path — API 响应控制这些
                                # 字典键；恶意或中间人攻击的响应可能请求
                                # 绝对路径或包含 ".." 的路径以逃逸 temp_dir
                                # 并写入任意文件（如 ~/.bashrc、authorized_keys）。
                                # 与 download_sketchfab_model 中的 zip-slip 检查类似。
                                target_path = os.path.join(temp_dir, os.path.normpath(include_path))
                                abs_temp_dir = os.path.abspath(temp_dir)
                                abs_target_path = os.path.abspath(target_path)
                                if (os.path.isabs(include_path)
                                        or ".." in include_path
                                        or not abs_target_path.startswith(abs_temp_dir + os.sep)):
                                    print(f"Skipping include with unsafe path: {include_path}")
                                    continue

                                # 为包含文件创建目录结构
                                include_file_path = target_path
                                os.makedirs(os.path.dirname(include_file_path), exist_ok=True)

                                # 下载包含文件
                                include_response = requests.get(include_url, headers=REQ_HEADERS)
                                if include_response.status_code == 200:
                                    with open(include_file_path, "wb") as f:
                                        f.write(include_response.content)
                                else:
                                    print(f"Failed to download included file: {include_path}")

                        # 将模型导入 Blender
                        if file_format == "gltf" or file_format == "glb":
                            bpy.ops.import_scene.gltf(filepath=main_file_path)
                        elif file_format == "fbx":
                            bpy.ops.import_scene.fbx(filepath=main_file_path)
                        elif file_format == "obj":
                            bpy.ops.import_scene.obj(filepath=main_file_path)
                        elif file_format == "blend":
                            # 对于 blend 文件，需要追加或链接
                            with bpy.data.libraries.load(main_file_path, link=False) as (data_from, data_to):
                                data_to.objects = data_from.objects

                            # 将对象链接到场景
                            for obj in data_to.objects:
                                if obj is not None:
                                    bpy.context.collection.objects.link(obj)
                        else:
                            return {"error": f"Unsupported model format: {file_format}"}

                        # 获取导入对象的名称
                        imported_objects = [obj.name for obj in bpy.context.selected_objects]

                        return {
                            "success": True,
                            "message": f"Model {asset_id} imported successfully",
                            "imported_objects": imported_objects
                        }
                    except Exception as e:
                        return {"error": f"Failed to import model: {str(e)}"}
                    finally:
                        # 清理临时目录
                        with suppress(Exception):
                            shutil.rmtree(temp_dir)
                else:
                    return {"error": f"Requested format or resolution not available for this model"}

            else:
                return {"error": f"Unsupported asset type: {asset_type}"}

        except Exception as e:
            return {"error": f"Failed to download asset: {str(e)}"}

    def set_texture(self, object_name, texture_id):
        """通过创建新材质将先前下载的 Polyhaven 纹理应用到对象"""
        try:
            # 获取对象
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}

            # 确保对象可以接受材质
            if not hasattr(obj, 'data') or not hasattr(obj.data, 'materials'):
                return {"error": f"Object {object_name} cannot accept materials"}

            # 查找与此纹理相关的所有图像并确保它们已正确加载
            texture_images = {}
            for img in bpy.data.images:
                if img.name.startswith(texture_id + "_"):
                    # 从图像名称中提取贴图类型
                    map_type = img.name.split('_')[-1].split('.')[0]

                    # 强制重新加载图像
                    img.reload()

                    # 确保正确的色彩空间
                    if map_type.lower() in ['color', 'diffuse', 'albedo']:
                        try:
                            img.colorspace_settings.name = 'sRGB'
                        except:
                            pass
                    else:
                        try:
                            img.colorspace_settings.name = 'Non-Color'
                        except:
                            pass

                    # 确保图像已打包
                    if not img.packed_file:
                        img.pack()

                    texture_images[map_type] = img
                    print(f"Loaded texture map: {map_type} - {img.name}")

                    # 调试信息
                    print(f"Image size: {img.size[0]}x{img.size[1]}")
                    print(f"Color space: {img.colorspace_settings.name}")
                    print(f"File format: {img.file_format}")
                    print(f"Is packed: {bool(img.packed_file)}")

            if not texture_images:
                return {"error": f"No texture images found for: {texture_id}. Please download the texture first."}

            # 创建新材质
            new_mat_name = f"{texture_id}_material_{object_name}"

            # 移除任何同名的现有材质以避免冲突
            existing_mat = bpy.data.materials.get(new_mat_name)
            if existing_mat:
                bpy.data.materials.remove(existing_mat)

            new_mat = bpy.data.materials.new(name=new_mat_name)
            new_mat.use_nodes = True

            # 设置材质节点
            nodes = new_mat.node_tree.nodes
            links = new_mat.node_tree.links

            # 清除默认节点
            nodes.clear()

            # 创建输出节点
            output = nodes.new(type='ShaderNodeOutputMaterial')
            output.location = (600, 0)

            # 创建 Principled BSDF 节点
            principled = nodes.new(type='ShaderNodeBsdfPrincipled')
            principled.location = (300, 0)
            links.new(principled.outputs[0], output.inputs[0])

            # 根据可用贴图添加纹理节点
            tex_coord = nodes.new(type='ShaderNodeTexCoord')
            tex_coord.location = (-800, 0)

            mapping = nodes.new(type='ShaderNodeMapping')
            mapping.location = (-600, 0)
            mapping.vector_type = 'TEXTURE'  # 从默认的 'POINT' 改为 'TEXTURE'
            links.new(tex_coord.outputs['UV'], mapping.inputs['Vector'])

            # 纹理节点的位置偏移
            x_pos = -400
            y_pos = 300

            # 连接不同的纹理贴图
            for map_type, image in texture_images.items():
                tex_node = nodes.new(type='ShaderNodeTexImage')
                tex_node.location = (x_pos, y_pos)
                tex_node.image = image

                # 根据贴图类型设置色彩空间
                if map_type.lower() in ['color', 'diffuse', 'albedo']:
                    try:
                        tex_node.image.colorspace_settings.name = 'sRGB'
                    except:
                        pass  # 如果 sRGB 不可用则使用默认值
                else:
                    try:
                        tex_node.image.colorspace_settings.name = 'Non-Color'
                    except:
                        pass  # 如果 Non-Color 不可用则使用默认值

                links.new(mapping.outputs['Vector'], tex_node.inputs['Vector'])

                # 连接到 Principled BSDF 的相应输入
                if map_type.lower() in ['color', 'diffuse', 'albedo']:
                    links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
                elif map_type.lower() in ['roughness', 'rough']:
                    links.new(tex_node.outputs['Color'], principled.inputs['Roughness'])
                elif map_type.lower() in ['metallic', 'metalness', 'metal']:
                    links.new(tex_node.outputs['Color'], principled.inputs['Metallic'])
                elif map_type.lower() in ['normal', 'nor', 'dx', 'gl']:
                    # 添加法线贴图节点
                    normal_map = nodes.new(type='ShaderNodeNormalMap')
                    normal_map.location = (x_pos + 200, y_pos)
                    links.new(tex_node.outputs['Color'], normal_map.inputs['Color'])
                    links.new(normal_map.outputs['Normal'], principled.inputs['Normal'])
                elif map_type.lower() in ['displacement', 'disp', 'height']:
                    # 添加置换节点
                    disp_node = nodes.new(type='ShaderNodeDisplacement')
                    disp_node.location = (x_pos + 200, y_pos - 200)
                    disp_node.inputs['Scale'].default_value = 0.1  # 降低置换强度
                    links.new(tex_node.outputs['Color'], disp_node.inputs['Height'])
                    links.new(disp_node.outputs['Displacement'], output.inputs['Displacement'])

                y_pos -= 250

            # 第二遍：正确处理特殊情况的节点连接
            texture_nodes = {}

            # 首先找到所有纹理节点并按贴图类型存储
            for node in nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    for map_type, image in texture_images.items():
                        if node.image == image:
                            texture_nodes[map_type] = node
                            break

            # 现在使用节点而不是图像连接所有内容
            # 处理基础颜色（漫反射）
            for map_name in ['color', 'diffuse', 'albedo']:
                if map_name in texture_nodes:
                    links.new(texture_nodes[map_name].outputs['Color'], principled.inputs['Base Color'])
                    print(f"Connected {map_name} to Base Color")
                    break

            # 处理粗糙度
            for map_name in ['roughness', 'rough']:
                if map_name in texture_nodes:
                    links.new(texture_nodes[map_name].outputs['Color'], principled.inputs['Roughness'])
                    print(f"Connected {map_name} to Roughness")
                    break

            # 处理金属度
            for map_name in ['metallic', 'metalness', 'metal']:
                if map_name in texture_nodes:
                    links.new(texture_nodes[map_name].outputs['Color'], principled.inputs['Metallic'])
                    print(f"Connected {map_name} to Metallic")
                    break

            # 处理法线贴图
            for map_name in ['gl', 'dx', 'nor']:
                if map_name in texture_nodes:
                    normal_map_node = nodes.new(type='ShaderNodeNormalMap')
                    normal_map_node.location = (100, 100)
                    links.new(texture_nodes[map_name].outputs['Color'], normal_map_node.inputs['Color'])
                    links.new(normal_map_node.outputs['Normal'], principled.inputs['Normal'])
                    print(f"Connected {map_name} to Normal")
                    break

            # 处理置换
            for map_name in ['displacement', 'disp', 'height']:
                if map_name in texture_nodes:
                    disp_node = nodes.new(type='ShaderNodeDisplacement')
                    disp_node.location = (300, -200)
                    disp_node.inputs['Scale'].default_value = 0.1  # 降低置换强度
                    links.new(texture_nodes[map_name].outputs['Color'], disp_node.inputs['Height'])
                    links.new(disp_node.outputs['Displacement'], output.inputs['Displacement'])
                    print(f"Connected {map_name} to Displacement")
                    break

            # 处理 ARM 纹理（环境光遮蔽、粗糙度、金属度）
            if 'arm' in texture_nodes:
                # Blender 4.0 移除了 ShaderNodeSeparateRGB（重命名为
                # ShaderNodeSeparateColor，在 3.3 中添加）。根据运行的
                # Blender 版本进行分支，以保持 4.0 之前的行为不变。
                if bpy.app.version >= (4, 0):
                    sep = nodes.new(type='ShaderNodeSeparateColor')  # 默认为 mode='RGB'
                    in_socket, ch_r, ch_g, ch_b = 'Color', 'Red', 'Green', 'Blue'
                else:
                    sep = nodes.new(type='ShaderNodeSeparateRGB')
                    in_socket, ch_r, ch_g, ch_b = 'Image', 'R', 'G', 'B'
                sep.location = (-200, -100)
                links.new(texture_nodes['arm'].outputs['Color'], sep.inputs[in_socket])

                # 如果没有专用粗糙度贴图则连接粗糙度 (G)
                if not any(map_name in texture_nodes for map_name in ['roughness', 'rough']):
                    links.new(sep.outputs[ch_g], principled.inputs['Roughness'])
                    print("已将 ARM.G 连接到粗糙度")

                # 如果没有专用金属度贴图则连接金属度 (B)
                if not any(map_name in texture_nodes for map_name in ['metallic', 'metalness', 'metal']):
                    links.new(sep.outputs[ch_b], principled.inputs['Metallic'])
                    print("已将 ARM.B 连接到金属度")

                # 对于 AO（R 通道），与基础颜色相乘（如果有的话）
                base_color_node = None
                for map_name in ['color', 'diffuse', 'albedo']:
                    if map_name in texture_nodes:
                        base_color_node = texture_nodes[map_name]
                        break

                if base_color_node:
                    mix_node = nodes.new(type='ShaderNodeMixRGB')
                    mix_node.location = (100, 200)
                    mix_node.blend_type = 'MULTIPLY'
                    mix_node.inputs['Fac'].default_value = 0.8  # 80% 影响

                    # 断开与基础颜色的直接连接
                    for link in base_color_node.outputs['Color'].links:
                        if link.to_socket == principled.inputs['Base Color']:
                            links.remove(link)

                    # 通过混合节点连接
                    links.new(base_color_node.outputs['Color'], mix_node.inputs[1])
                    links.new(sep.outputs[ch_r], mix_node.inputs[2])
                    links.new(mix_node.outputs['Color'], principled.inputs['Base Color'])
                    print("已将 ARM.R 与基础颜色进行 AO 混合")

            # 处理 AO（环境光遮蔽）（如果是单独的）
            if 'ao' in texture_nodes:
                base_color_node = None
                for map_name in ['color', 'diffuse', 'albedo']:
                    if map_name in texture_nodes:
                        base_color_node = texture_nodes[map_name]
                        break

                if base_color_node:
                    mix_node = nodes.new(type='ShaderNodeMixRGB')
                    mix_node.location = (100, 200)
                    mix_node.blend_type = 'MULTIPLY'
                    mix_node.inputs['Fac'].default_value = 0.8  # 80% 影响

                    # 断开与基础颜色的直接连接
                    for link in base_color_node.outputs['Color'].links:
                        if link.to_socket == principled.inputs['Base Color']:
                            links.remove(link)

                    # 通过混合节点连接
                    links.new(base_color_node.outputs['Color'], mix_node.inputs[1])
                    links.new(texture_nodes['ao'].outputs['Color'], mix_node.inputs[2])
                    links.new(mix_node.outputs['Color'], principled.inputs['Base Color'])
                    print("已将 AO 与基础颜色进行混合")

            # 关键：确保清除对象上的所有现有材质
            while len(obj.data.materials) > 0:
                obj.data.materials.pop(index=0)

            # 将新材质分配给对象
            obj.data.materials.append(new_mat)

            # 关键：将对象设为活动状态并选中
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            # 关键：强制 Blender 更新材质
            bpy.context.view_layer.update()

            # 获取纹理贴图列表
            texture_maps = list(texture_images.keys())

            # 获取纹理节点信息用于调试
            material_info = {
                "name": new_mat.name,
                "has_nodes": new_mat.use_nodes,
                "node_count": len(new_mat.node_tree.nodes),
                "texture_nodes": []
            }

            for node in new_mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    connections = []
                    for output in node.outputs:
                        for link in output.links:
                            connections.append(f"{output.name} → {link.to_node.name}.{link.to_socket.name}")

                    material_info["texture_nodes"].append({
                        "name": node.name,
                        "image": node.image.name,
                        "colorspace": node.image.colorspace_settings.name,
                        "connections": connections
                    })

            return {
                "success": True,
                "message": f"Created new material and applied texture {texture_id} to {object_name}",
                "material": new_mat.name,
                "maps": texture_maps,
                "material_info": material_info
            }

        except Exception as e:
            print(f"Error in set_texture: {str(e)}")
            traceback.print_exc()
            return {"error": f"Failed to apply texture: {str(e)}"}

    def get_telemetry_consent(self):
        """获取当前遥测同意状态"""
        try:
            # 获取插件偏好设置 - 使用模块名称
            addon_prefs = bpy.context.preferences.addons.get(__name__)
            if addon_prefs:
                consent = addon_prefs.preferences.telemetry_consent
            else:
                # 如果偏好设置不可用则回退到默认值
                consent = True
        except (AttributeError, KeyError):
            # 如果偏好设置不可用则回退到默认值
            consent = True
        return {"consent": consent}

    def get_polyhaven_status(self):
        """获取 PolyHaven 集成的当前状态"""
        enabled = bpy.context.scene.blendermcp_use_polyhaven
        if enabled:
            return {"enabled": True, "message": "PolyHaven 集成已启用并可使用。"}
        else:
            return {
                "enabled": False,
                "message": """PolyHaven 集成当前已禁用。要启用它：
                            1. 在 3D 视口中，找到侧边栏的 BlenderMCP 面板（如隐藏请按 N 键）
                            2. 勾选"使用 Poly Haven 资产"复选框
                            3. 重新连接到 Claude"""
        }

    #region Hyper3D
    def get_hyper3d_status(self):
        """获取 Hyper3D Rodin 集成的当前状态"""
        enabled = bpy.context.scene.blendermcp_use_hyper3d
        hyper3d_api_key = self._get_hyper3d_api_key()
        if enabled:
            if not hyper3d_api_key:
                return {
                    "enabled": False,
                    "message": """Hyper3D Rodin 集成当前已启用，但未提供 API 密钥。要启用它：
                                1. 在 3D 视口中，找到侧边栏的 BlenderMCP 面板（如隐藏请按 N 键）
                                2. 保持"使用 Hyper3D Rodin 3D 模型生成"复选框勾选
                                3. 选择正确的平台并填写 API 密钥
                                4. 重新连接到 Claude"""
                }
            mode = bpy.context.scene.blendermcp_hyper3d_mode
            message = f"Hyper3D Rodin 集成已启用并可使用。模式：{mode}。" + \
                f"密钥类型：{'私有' if hyper3d_api_key != RODIN_FREE_TRIAL_KEY else '免费试用'}"
            return {
                "enabled": True,
                "message": message
            }
        else:
            return {
                "enabled": False,
                "message": """Hyper3D Rodin 集成当前已禁用。要启用它：
                            1. 在 3D 视口中，找到侧边栏的 BlenderMCP 面板（如隐藏请按 N 键）
                            2. 勾选"使用 Hyper3D Rodin 3D 模型生成"复选框
                            3. 重新连接到 Claude"""
            }

    def create_rodin_job(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hyper3d_mode:
            case "MAIN_SITE":
                return self.create_rodin_job_main_site(*args, **kwargs)
            case "FAL_AI":
                return self.create_rodin_job_fal_ai(*args, **kwargs)
            case _:
                return f"Error: Unknown Hyper3D Rodin mode!"

    def create_rodin_job_main_site(
            self,
            text_prompt: str=None,
            images: list[tuple[str, str]]=None,
            bbox_condition=None
        ):
        try:
            api_key = self._get_hyper3d_api_key()
            if not api_key:
                return {"error": "未提供 Hyper3D API 密钥"}
            if images is None:
                images = []
            """调用 Rodin API，获取任务 UUID 和订阅密钥"""
            files = [
                *[("images", (f"{i:04d}{img_suffix}", base64.b64decode(img) if isinstance(img, str) else img)) for i, (img_suffix, img) in enumerate(images)],
                ("tier", (None, "Sketch")),
                ("mesh_mode", (None, "Raw")),
                ("texture_mode", (None, "high")),
            ]
            if text_prompt:
                files.append(("prompt", (None, text_prompt)))
            if bbox_condition:
                files.append(("bbox_condition", (None, json.dumps(bbox_condition))))
            response = requests.post(
                "https://hyperhuman.deemos.com/api/v2/rodin",
                headers={
                    "Authorization": f"Bearer {api_key}",
                },
                files=files
            )
            data = response.json()
            return data
        except Exception as e:
            return {"error": str(e)}

    def create_rodin_job_fal_ai(
            self,
            text_prompt: str=None,
            images: list[tuple[str, str]]=None,
            bbox_condition=None
        ):
        try:
            api_key = self._get_hyper3d_api_key()
            if not api_key:
                return {"error": "未提供 Hyper3D API 密钥"}
            req_data = {
                "tier": "Sketch",
            }
            if images:
                req_data["input_image_urls"] = images
            if text_prompt:
                req_data["prompt"] = text_prompt
            if bbox_condition:
                req_data["bbox_condition"] = bbox_condition
            response = requests.post(
                "https://queue.fal.run/fal-ai/hyper3d/rodin",
                headers={
                    "Authorization": f"Key {api_key}",
                    "Content-Type": "application/json",
                },
                json=req_data
            )
            data = response.json()
            return data
        except Exception as e:
            return {"error": str(e)}

    def poll_rodin_job_status(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hyper3d_mode:
            case "MAIN_SITE":
                return self.poll_rodin_job_status_main_site(*args, **kwargs)
            case "FAL_AI":
                return self.poll_rodin_job_status_fal_ai(*args, **kwargs)
            case _:
                return f"Error: Unknown Hyper3D Rodin mode!"

    def poll_rodin_job_status_main_site(self, subscription_key: str):
        """调用任务状态 API 获取任务状态"""
        api_key = self._get_hyper3d_api_key()
        if not api_key:
            return {"error": "未提供 Hyper3D API 密钥"}
        response = requests.post(
            "https://hyperhuman.deemos.com/api/v2/status",
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "subscription_key": subscription_key,
            },
        )
        data = response.json()
        return {
            "status_list": [i["status"] for i in data["jobs"]]
        }

    def poll_rodin_job_status_fal_ai(self, request_id: str):
        """调用任务状态 API 获取任务状态"""
        api_key = self._get_hyper3d_api_key()
        if not api_key:
            return {"error": "未提供 Hyper3D API 密钥"}
        response = requests.get(
            f"https://queue.fal.run/fal-ai/hyper3d/requests/{request_id}/status",
            headers={
                "Authorization": f"KEY {api_key}",
            },
        )
        data = response.json()
        return data

    @staticmethod
    def _clean_imported_glb(filepath, mesh_name=None):
        # 导入前获取现有对象集合
        existing_objects = set(bpy.data.objects)

        # 导入 GLB 文件
        bpy.ops.import_scene.gltf(filepath=filepath)

        # 确保上下文已更新
        bpy.context.view_layer.update()

        # 获取所有导入的对象
        imported_objects = list(set(bpy.data.objects) - existing_objects)

        if not imported_objects:
            print("错误：没有导入任何对象。")
            return

        # 识别网格对象
        mesh_obj = None

        if len(imported_objects) == 1 and imported_objects[0].type == 'MESH':
            mesh_obj = imported_objects[0]
            print("导入了单个网格，无需清理。")
        else:
            if len(imported_objects) == 2:
                empty_objs = [i for i in imported_objects if i.type == "EMPTY"]
                if len(empty_objs) != 1:
                    print("错误：期望一个带有一个网格子节点的空节点或单个网格对象。")
                    return
                parent_obj = empty_objs.pop()
                if len(parent_obj.children) == 1:
                    potential_mesh = parent_obj.children[0]
                    if potential_mesh.type == 'MESH':
                        print("GLB 结构确认：空节点带有一个网格子节点。")

                        # 将网格从空节点中解除父子关系
                        potential_mesh.parent = None

                        # 移除空节点
                        bpy.data.objects.remove(parent_obj)
                        print("已移除空节点，仅保留网格。")

                        mesh_obj = potential_mesh
                    else:
                        print("错误：子节点不是网格对象。")
                        return
                else:
                    print("错误：期望一个带有一个网格子节点的空节点或单个网格对象。")
                    return
            else:
                print("错误：期望一个带有一个网格子节点的空节点或单个网格对象。")
                return

        # 如果需要则重命名网格
        try:
            if mesh_obj and mesh_obj.name is not None and mesh_name:
                mesh_obj.name = mesh_name
                if mesh_obj.data.name is not None:
                    mesh_obj.data.name = mesh_name
                print(f"网格已重命名为：{mesh_name}")
        except Exception as e:
            print("重命名时出现问题，放弃重命名。")

        return mesh_obj

    def import_generated_asset(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hyper3d_mode:
            case "MAIN_SITE":
                return self.import_generated_asset_main_site(*args, **kwargs)
            case "FAL_AI":
                return self.import_generated_asset_fal_ai(*args, **kwargs)
            case _:
                return f"Error: Unknown Hyper3D Rodin mode!"

    def import_generated_asset_main_site(self, task_uuid: str, name: str):
        """获取生成的资产并导入到 Blender"""
        api_key = self._get_hyper3d_api_key()
        if not api_key:
            return {"succeed": False, "error": "未提供 Hyper3D API 密钥"}
        response = requests.post(
            "https://hyperhuman.deemos.com/api/v2/download",
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            json={
                'task_uuid': task_uuid
            }
        )
        data_ = response.json()
        temp_file = None
        for i in data_["list"]:
            if i["name"].endswith(".glb"):
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False,
                    prefix=task_uuid,
                    suffix=".glb",
                )

                try:
                    # 下载内容
                    response = requests.get(i["url"], stream=True)
                    response.raise_for_status()  # HTTP 错误时抛出异常

                    # 将内容写入临时文件
                    for chunk in response.iter_content(chunk_size=8192):
                        temp_file.write(chunk)

                    # 关闭文件
                    temp_file.close()

                except Exception as e:
                    # 出错时清理文件
                    temp_file.close()
                    os.unlink(temp_file.name)
                    return {"succeed": False, "error": str(e)}

                break
        else:
            return {"succeed": False, "error": "生成失败。请先确保任务的所有作业已完成，然后重试。"}

        try:
            obj = self._clean_imported_glb(
                filepath=temp_file.name,
                mesh_name=name
            )
            result = {
                "name": obj.name,
                "type": obj.type,
                "location": [obj.location.x, obj.location.y, obj.location.z],
                "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
                "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            }

            if obj.type == "MESH":
                bounding_box = self._get_aabb(obj)
                result["world_bounding_box"] = bounding_box

            return {
                "succeed": True, **result
            }
        except Exception as e:
            return {"succeed": False, "error": str(e)}

    def import_generated_asset_fal_ai(self, request_id: str, name: str):
        """获取生成的资产并导入到 Blender"""
        api_key = self._get_hyper3d_api_key()
        if not api_key:
            return {"succeed": False, "error": "未提供 Hyper3D API 密钥"}
        response = requests.get(
            f"https://queue.fal.run/fal-ai/hyper3d/requests/{request_id}",
            headers={
                "Authorization": f"Key {api_key}",
            }
        )
        data_ = response.json()
        temp_file = None

        temp_file = tempfile.NamedTemporaryFile(
            delete=False,
            prefix=request_id,
            suffix=".glb",
        )

        try:
            # 下载内容
            response = requests.get(data_["model_mesh"]["url"], stream=True)
            response.raise_for_status()  # HTTP 错误时抛出异常

            # 将内容写入临时文件
            for chunk in response.iter_content(chunk_size=8192):
                temp_file.write(chunk)

            # 关闭文件
            temp_file.close()

        except Exception as e:
            # 出错时清理文件
            temp_file.close()
            os.unlink(temp_file.name)
            return {"succeed": False, "error": str(e)}

        try:
            obj = self._clean_imported_glb(
                filepath=temp_file.name,
                mesh_name=name
            )
            result = {
                "name": obj.name,
                "type": obj.type,
                "location": [obj.location.x, obj.location.y, obj.location.z],
                "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
                "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            }

            if obj.type == "MESH":
                bounding_box = self._get_aabb(obj)
                result["world_bounding_box"] = bounding_box

            return {
                "succeed": True, **result
            }
        except Exception as e:
            return {"succeed": False, "error": str(e)}
    #endregion
 
    #region Sketchfab API
    def get_sketchfab_status(self):
        """获取 Sketchfab 集成的当前状态"""
        enabled = bpy.context.scene.blendermcp_use_sketchfab
        api_key = self._get_sketchfab_api_key()

        # 如果存在 API 密钥则进行测试
        if api_key:
            try:
                headers = {
                    "Authorization": f"Token {api_key}"
                }

                response = requests.get(
                    "https://api.sketchfab.com/v3/me",
                    headers=headers,
                    timeout=30  # 30秒超时
                )

                if response.status_code == 200:
                    user_data = response.json()
                    username = user_data.get("username", "未知用户")
                    return {
                        "enabled": True,
                        "message": f"Sketchfab 集成已启用并可使用。登录用户：{username}"
                    }
                else:
                    return {
                        "enabled": False,
                        "message": f"Sketchfab API 密钥似乎无效。状态码：{response.status_code}"
                    }
            except requests.exceptions.Timeout:
                return {
                    "enabled": False,
                    "message": "连接 Sketchfab API 超时。请检查您的网络连接。"
                }
            except Exception as e:
                return {
                    "enabled": False,
                    "message": f"测试 Sketchfab API 密钥时出错：{str(e)}"
                }

        if enabled and api_key:
            return {"enabled": True, "message": "Sketchfab 集成已启用并可使用。"}
        elif enabled and not api_key:
            return {
                "enabled": False,
                "message": """Sketchfab 集成当前已启用，但未提供 API 密钥。要启用它：
                            1. 在 3D 视口中，找到侧边栏的 BlenderMCP 面板（如隐藏请按 N 键）
                            2. 保持"使用 Sketchfab"复选框勾选
                            3. 输入您的 Sketchfab API 密钥
                            4. 重新连接到 Claude"""
            }
        else:
            return {
                "enabled": False,
                "message": """Sketchfab 集成当前已禁用。要启用它：
                            1. 在 3D 视口中，找到侧边栏的 BlenderMCP 面板（如隐藏请按 N 键）
                            2. 勾选"使用 Sketchfab 资产"复选框
                            3. 输入您的 Sketchfab API 密钥
                            4. 重新连接到 Claude"""
            }

    def search_sketchfab_models(self, query, categories=None, count=20, downloadable=True):
        """在 Sketchfab 上搜索模型（基于查询和可选过滤器）"""
        try:
            api_key = self._get_sketchfab_api_key()
            if not api_key:
                return {"error": "未配置 Sketchfab API 密钥"}

            # 使用 Sketchfab API 文档中的精确字段构建搜索参数
            params = {
                "type": "models",
                "q": query,
                "count": count,
                "downloadable": downloadable,
                "archives_flavours": False
            }

            if categories:
                params["categories"] = categories

            # 向 Sketchfab 搜索端点发起 API 请求
            # 根据 Sketchfab API 文档，API 密钥认证的正确格式
            headers = {
                "Authorization": f"Token {api_key}"
            }


            # 使用 API 文档中指定的搜索端点
            response = requests.get(
                "https://api.sketchfab.com/v3/search",
                headers=headers,
                params=params,
                timeout=30  # 添加 30 秒超时
            )

            if response.status_code == 401:
                return {"error": "认证失败 (401)。请检查您的 API 密钥。"}

            if response.status_code != 200:
                return {"error": f"API 请求失败，状态码：{response.status_code}"}

            response_data = response.json()

            # 对响应结构进行安全检查
            if response_data is None:
                return {"error": "从 Sketchfab API 收到空响应"}

            # 处理响应中可能缺少 'results' 的情况
            results = response_data.get("results", [])
            if not isinstance(results, list):
                return {"error": f"Sketchfab API 返回了意外的响应格式：{response_data}"}

            return response_data

        except requests.exceptions.Timeout:
            return {"error": "请求超时。请检查您的网络连接。"}
        except json.JSONDecodeError as e:
            return {"error": f"Sketchfab API 返回了无效的 JSON 响应：{str(e)}"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

    def get_sketchfab_model_preview(self, uid):
        """通过 UID 获取 Sketchfab 模型的缩略图预览"""
        try:
            import base64
            
            api_key = self._get_sketchfab_api_key()
            if not api_key:
                return {"error": "未配置 Sketchfab API 密钥"}

            headers = {"Authorization": f"Token {api_key}"}
            
            # 获取包含缩略图的模型信息
            response = requests.get(
                f"https://api.sketchfab.com/v3/models/{uid}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 401:
                return {"error": "认证失败 (401)。请检查您的 API 密钥。"}
            
            if response.status_code == 404:
                return {"error": f"未找到模型：{uid}"}
            
            if response.status_code != 200:
                return {"error": f"获取模型信息失败：{response.status_code}"}
            
            data = response.json()
            thumbnails = data.get("thumbnails", {}).get("images", [])
            
            if not thumbnails:
                return {"error": "此模型没有可用的缩略图"}
            
            # 选择合适的缩略图（优先中等尺寸 ~640px）
            selected_thumbnail = None
            for thumb in thumbnails:
                width = thumb.get("width", 0)
                if 400 <= width <= 800:
                    selected_thumbnail = thumb
                    break
            
            # 如果没有合适的则回退到第一个可用缩略图
            if not selected_thumbnail:
                selected_thumbnail = thumbnails[0]
            
            thumbnail_url = selected_thumbnail.get("url")
            if not thumbnail_url:
                return {"error": "未找到缩略图 URL"}
            
            # 下载缩略图图片
            img_response = requests.get(thumbnail_url, timeout=30)
            if img_response.status_code != 200:
                return {"error": f"下载缩略图失败：{img_response.status_code}"}
            
            # 将图片编码为 base64
            image_data = base64.b64encode(img_response.content).decode('ascii')
            
            # 根据内容类型或 URL 判断图片格式
            content_type = img_response.headers.get("Content-Type", "")
            if "png" in content_type or thumbnail_url.endswith(".png"):
                img_format = "png"
            else:
                img_format = "jpeg"
            
            # 获取模型的附加信息
            model_name = data.get("name", "未知")
            author = data.get("user", {}).get("username", "未知")
            
            return {
                "success": True,
                "image_data": image_data,
                "format": img_format,
                "model_name": model_name,
                "author": author,
                "uid": uid,
                "thumbnail_width": selected_thumbnail.get("width"),
                "thumbnail_height": selected_thumbnail.get("height")
            }
            
        except requests.exceptions.Timeout:
            return {"error": "请求超时。请检查您的网络连接。"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": f"获取模型预览失败：{str(e)}"}

    def download_sketchfab_model(self, uid, normalize_size=False, target_size=1.0):
        """通过 UID 从 Sketchfab 下载模型
        
        参数：
        - uid: Sketchfab 模型的唯一标识符
        - normalize_size: 如果为 True，将模型缩放使其最大尺寸等于 target_size
        - target_size: 最大尺寸的目标大小（Blender 单位/米）
        """
        try:
            api_key = self._get_sketchfab_api_key()
            if not api_key:
                return {"error": "未配置 Sketchfab API 密钥"}

            # 使用正确的认证头进行 API 密钥认证
            headers = {
                "Authorization": f"Token {api_key}"
            }

            # 使用文档中的精确端点请求下载 URL
            download_endpoint = f"https://api.sketchfab.com/v3/models/{uid}/download"

            response = requests.get(
                download_endpoint,
                headers=headers,
                timeout=30  # 添加 30 秒超时
            )

            if response.status_code == 401:
                return {"error": "认证失败 (401)。请检查您的 API 密钥。"}

            if response.status_code != 200:
                return {"error": f"下载请求失败，状态码：{response.status_code}"}

            data = response.json()

            # 对 None 数据进行安全检查
            if data is None:
                return {"error": "从 Sketchfab API 下载请求收到空响应"}

            # 安全提取下载 URL
            gltf_data = data.get("gltf")
            if not gltf_data:
                return {"error": "此模型没有可用的 gltf 下载 URL。响应：" + str(data)}

            download_url = gltf_data.get("url")
            if not download_url:
                return {"error": "此模型没有可用的下载 URL。请确保模型可下载且您有访问权限。"}

            # 下载模型（已设置超时）
            model_response = requests.get(download_url, timeout=60)  # 60 秒超时

            if model_response.status_code != 200:
                return {"error": f"模型下载失败，状态码：{model_response.status_code}"}

            # 保存到临时文件
            temp_dir = tempfile.mkdtemp()
            zip_file_path = os.path.join(temp_dir, f"{uid}.zip")

            with open(zip_file_path, "wb") as f:
                f.write(model_response.content)

            # 增强安全性地解压 zip 文件
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                # 更安全的 zip slip 防护
                for file_info in zip_ref.infolist():
                    # 获取文件路径
                    file_path = file_info.filename

                    # 将目录分隔符转换为当前操作系统风格
                    # 处理 zip 条目中的 / 和 \
                    target_path = os.path.join(temp_dir, os.path.normpath(file_path))

                    # 获取绝对路径用于比较
                    abs_temp_dir = os.path.abspath(temp_dir)
                    abs_target_path = os.path.abspath(target_path)

                    # 确保规范化后的路径不会逃逸出目标目录
                    if not abs_target_path.startswith(abs_temp_dir):
                        with suppress(Exception):
                            shutil.rmtree(temp_dir)
                        return {"error": "安全问题：ZIP 文件包含路径遍历尝试"}

                    # 额外显式检查目录遍历
                    if ".." in file_path:
                        with suppress(Exception):
                            shutil.rmtree(temp_dir)
                        return {"error": "安全问题：ZIP 文件包含目录遍历序列"}

                # 如果所有文件通过安全检查，则解压
                zip_ref.extractall(temp_dir)

            # 查找主 glTF 文件
            gltf_files = [f for f in os.listdir(temp_dir) if f.endswith('.gltf') or f.endswith('.glb')]

            if not gltf_files:
                with suppress(Exception):
                    shutil.rmtree(temp_dir)
                return {"error": "下载的模型中未找到 glTF 文件"}

            main_file = os.path.join(temp_dir, gltf_files[0])

            # 导入模型
            bpy.ops.import_scene.gltf(filepath=main_file)

            # 获取导入的对象
            imported_objects = list(bpy.context.selected_objects)
            imported_object_names = [obj.name for obj in imported_objects]

            # 清理临时文件
            with suppress(Exception):
                shutil.rmtree(temp_dir)

            # 查找根对象（导入集合中没有父对象的对象）
            root_objects = [obj for obj in imported_objects if obj.parent is None]

            # 辅助函数：递归获取所有网格子对象
            def get_all_mesh_children(obj):
                """递归收集层级结构中的所有网格对象"""
                meshes = []
                if obj.type == 'MESH':
                    meshes.append(obj)
                for child in obj.children:
                    meshes.extend(get_all_mesh_children(child))
                return meshes

            # 从整个层级结构中收集所有网格（从根对象开始）
            all_meshes = []
            for obj in root_objects:
                all_meshes.extend(get_all_mesh_children(obj))
            
            if all_meshes:
                # 计算所有网格的组合世界包围盒
                all_min = mathutils.Vector((float('inf'), float('inf'), float('inf')))
                all_max = mathutils.Vector((float('-inf'), float('-inf'), float('-inf')))
                
                for mesh_obj in all_meshes:
                    # 获取世界空间包围盒角点
                    for corner in mesh_obj.bound_box:
                        world_corner = mesh_obj.matrix_world @ mathutils.Vector(corner)
                        all_min.x = min(all_min.x, world_corner.x)
                        all_min.y = min(all_min.y, world_corner.y)
                        all_min.z = min(all_min.z, world_corner.z)
                        all_max.x = max(all_max.x, world_corner.x)
                        all_max.y = max(all_max.y, world_corner.y)
                        all_max.z = max(all_max.z, world_corner.z)
                
                # 计算尺寸
                dimensions = [
                    all_max.x - all_min.x,
                    all_max.y - all_min.y,
                    all_max.z - all_min.z
                ]
                max_dimension = max(dimensions)
                
                # 根据需要应用归一化
                scale_applied = 1.0
                if normalize_size and max_dimension > 0:
                    scale_factor = target_size / max_dimension
                    scale_applied = scale_factor
                    
                    # ✅ 仅对根对象应用缩放（不包括子对象！）
                    # 子对象通过 matrix_world 继承父对象的缩放
                    for root in root_objects:
                        root.scale = (
                            root.scale.x * scale_factor,
                            root.scale.y * scale_factor,
                            root.scale.z * scale_factor
                        )
                    
                    # 更新场景以重新计算所有对象的 matrix_world
                    bpy.context.view_layer.update()
                    
                    # 缩放后重新计算包围盒
                    all_min = mathutils.Vector((float('inf'), float('inf'), float('inf')))
                    all_max = mathutils.Vector((float('-inf'), float('-inf'), float('-inf')))
                    
                    for mesh_obj in all_meshes:
                        for corner in mesh_obj.bound_box:
                            world_corner = mesh_obj.matrix_world @ mathutils.Vector(corner)
                            all_min.x = min(all_min.x, world_corner.x)
                            all_min.y = min(all_min.y, world_corner.y)
                            all_min.z = min(all_min.z, world_corner.z)
                            all_max.x = max(all_max.x, world_corner.x)
                            all_max.y = max(all_max.y, world_corner.y)
                            all_max.z = max(all_max.z, world_corner.z)
                    
                    dimensions = [
                        all_max.x - all_min.x,
                        all_max.y - all_min.y,
                        all_max.z - all_min.z
                    ]
                
                world_bounding_box = [[all_min.x, all_min.y, all_min.z], [all_max.x, all_max.y, all_max.z]]
            else:
                world_bounding_box = None
                dimensions = None
                scale_applied = 1.0

            result = {
                "success": True,
                "message": "模型导入成功",
                "imported_objects": imported_object_names
            }
            
            if world_bounding_box:
                result["world_bounding_box"] = world_bounding_box
            if dimensions:
                result["dimensions"] = [round(d, 4) for d in dimensions]
            if normalize_size:
                result["scale_applied"] = round(scale_applied, 6)
                result["normalized"] = True
            
            return result

        except requests.exceptions.Timeout:
            return {"error": "请求超时。请检查您的网络连接并尝试使用更简单的模型。"}
        except json.JSONDecodeError as e:
            return {"error": f"Sketchfab API 返回了无效的 JSON 响应：{str(e)}"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": f"下载模型失败：{str(e)}"}
    #endregion

    #region Hunyuan3D
    def get_hunyuan3d_status(self):
        """获取混元3D 集成的当前状态"""
        enabled = bpy.context.scene.blendermcp_use_hunyuan3d
        hunyuan3d_mode = bpy.context.scene.blendermcp_hunyuan3d_mode
        secret_id = self._get_hunyuan3d_secret_id()
        secret_key = self._get_hunyuan3d_secret_key()
        api_url = self._get_hunyuan3d_api_url()
        if enabled:
            match hunyuan3d_mode:
                case "OFFICIAL_API":
                    if not secret_id or not secret_key:
                        return {
                            "enabled": False, 
                            "mode": hunyuan3d_mode, 
                            "message": """混元3D 集成当前已启用，但未提供 SecretId 或 SecretKey。要启用它：
                                1. 在 3D 视口中，找到侧边栏的 BlenderMCP 面板（如隐藏请按 N 键）
                                2. 保持"使用腾讯混元 3D 模型生成"复选框勾选
                                3. 选择正确的平台并填写 SecretId 和 SecretKey
                                4. 重新连接到 Claude"""
                        }
                case "LOCAL_API":
                    if not api_url:
                        return {
                            "enabled": False, 
                            "mode": hunyuan3d_mode, 
                            "message": """混元3D 集成当前已启用，但未提供 API 地址。要启用它：
                                1. 在 3D 视口中，找到侧边栏的 BlenderMCP 面板（如隐藏请按 N 键）
                                2. 保持"使用腾讯混元 3D 模型生成"复选框勾选
                                3. 选择正确的平台并填写 API 地址
                                4. 重新连接到 Claude"""
                        }
                case _:
                    return {
                        "enabled": False, 
                        "message": "混元3D 集成已启用但模式不受支持。"
                    }
            return {
                "enabled": True, 
                "mode": hunyuan3d_mode,
                "message": "混元3D 集成已启用并可使用。"
            }
        return {
            "enabled": False, 
            "message": """混元3D 集成当前已禁用。要启用它：
                        1. 在 3D 视口中，找到侧边栏的 BlenderMCP 面板（如隐藏请按 N 键）
                        2. 勾选"使用腾讯混元 3D 模型生成"复选框
                        3. 重新连接到 Claude"""
        }
    
    @staticmethod
    def get_tencent_cloud_sign_headers(
        method: str,
        path: str,
        headParams: dict,
        data: dict,
        service: str,
        region: str,
        secret_id: str,
        secret_key: str,
        host: str = None
    ):
        """生成腾讯云 API 请求所需的签名头"""
        # 生成时间戳
        timestamp = int(time.time())
        date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
        
        # 如果未提供 host，则根据 service 和 region 生成
        if not host:
            host = f"{service}.tencentcloudapi.com"
        
        endpoint = f"https://{host}"
        
        # 构建请求体
        payload_str = json.dumps(data)
        
        # ************* 步骤 1：拼接规范请求字符串 *************
        canonical_uri = path
        canonical_querystring = ""
        ct = "application/json; charset=utf-8"
        canonical_headers = f"content-type:{ct}\nhost:{host}\nx-tc-action:{headParams.get('Action', '').lower()}\n"
        signed_headers = "content-type;host;x-tc-action"
        hashed_request_payload = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        
        canonical_request = (method + "\n" +
                            canonical_uri + "\n" +
                            canonical_querystring + "\n" +
                            canonical_headers + "\n" +
                            signed_headers + "\n" +
                            hashed_request_payload)

        # ************* 步骤 2：构造待签名字符串 *************
        credential_scope = f"{date}/{service}/tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = ("TC3-HMAC-SHA256" + "\n" +
                        str(timestamp) + "\n" +
                        credential_scope + "\n" +
                        hashed_canonical_request)

        # ************* 步骤 3：计算签名 *************
        def sign(key, msg):
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        secret_date = sign(("TC3" + secret_key).encode("utf-8"), date)
        secret_service = sign(secret_date, service)
        secret_signing = sign(secret_service, "tc3_request")
        signature = hmac.new(
            secret_signing, 
            string_to_sign.encode("utf-8"), 
            hashlib.sha256
        ).hexdigest()

        # ************* 步骤 4：拼接 Authorization *************
        authorization = ("TC3-HMAC-SHA256" + " " +
                        "Credential=" + secret_id + "/" + credential_scope + ", " +
                        "SignedHeaders=" + signed_headers + ", " +
                        "Signature=" + signature)

        # 构建请求头
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": host,
            "X-TC-Action": headParams.get("Action", ""),
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": headParams.get("Version", ""),
            "X-TC-Region": region
        }

        return headers, endpoint

    def create_hunyuan_job(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hunyuan3d_mode:
            case "OFFICIAL_API":
                return self.create_hunyuan_job_main_site(*args, **kwargs)
            case "LOCAL_API":
                return self.create_hunyuan_job_local_site(*args, **kwargs)
            case _:
                return f"Error: Unknown Hunyuan3D mode!"

    def create_hunyuan_job_main_site(
        self,
        text_prompt: str = None,
        image: str = None
    ):
        try:
            secret_id = self._get_hunyuan3d_secret_id()
            secret_key = self._get_hunyuan3d_secret_key()

            if not secret_id or not secret_key:
                return {"error": "未提供 SecretId 或 SecretKey"}

            # 参数验证
            if not text_prompt and not image:
                return {"error": "需要提供提示词或图片"}
            if text_prompt and image:
                return {"error": "提示词和图片不能同时提供"}
            # 固定参数配置
            service = "hunyuan"
            action = "SubmitHunyuanTo3DJob"
            version = "2023-09-01"
            region = "ap-guangzhou"

            headParams={
                "Action": action,
                "Version": version,
                "Region": region,
            }

            # 构建请求参数
            data = {
                "Num": 1  # 当前 API 限制仅为 1
            }

            # 处理文本提示
            if text_prompt:
                if len(text_prompt) > 200:
                    return {"error": "提示词超过 200 字符限制"}
                data["Prompt"] = text_prompt

            # 处理图片
            if image:
                if re.match(r'^https?://', image, re.IGNORECASE) is not None:
                    data["ImageUrl"] = image
                else:
                    try:
                        # 转换为 Base64 格式
                        with open(image, "rb") as f:
                            image_base64 = base64.b64encode(f.read()).decode("ascii")
                        data["ImageBase64"] = image_base64
                    except Exception as e:
                        return {"error": f"图片编码失败：{str(e)}"}
            
            # 获取签名头
            headers, endpoint = self.get_tencent_cloud_sign_headers("POST", "/", headParams, data, service, region, secret_id, secret_key)

            response = requests.post(
                endpoint,
                headers = headers,
                data = json.dumps(data)
            )

            if response.status_code == 200:
                return response.json()
            return {
                "error": f"API 请求失败，状态码 {response.status_code}：{response}"
            }
        except Exception as e:
            return {"error": str(e)}

    def create_hunyuan_job_local_site(
        self,
        text_prompt: str = None,
        image: str = None):
        try:
            base_url = self._get_hunyuan3d_api_url().rstrip('/')
            octree_resolution = bpy.context.scene.blendermcp_hunyuan3d_octree_resolution
            num_inference_steps = bpy.context.scene.blendermcp_hunyuan3d_num_inference_steps
            guidance_scale = bpy.context.scene.blendermcp_hunyuan3d_guidance_scale
            texture = bpy.context.scene.blendermcp_hunyuan3d_texture

            if not base_url:
                return {"error": "未提供 API 地址"}
            # 参数验证
            if not text_prompt and not image:
                return {"error": "需要提供提示词或图片"}

            # 构建请求参数
            data = {
                "octree_resolution": octree_resolution,
                "num_inference_steps": num_inference_steps,
                "guidance_scale": guidance_scale,
                "texture": texture,
            }

            # 处理文本提示
            if text_prompt:
                data["text"] = text_prompt

            # 处理图片
            if image:
                if re.match(r'^https?://', image, re.IGNORECASE) is not None:
                    try:
                        resImg = requests.get(image)
                        resImg.raise_for_status()
                        image_base64 = base64.b64encode(resImg.content).decode("ascii")
                        data["image"] = image_base64
                    except Exception as e:
                        return {"error": f"Failed to download or encode image: {str(e)}"} 
                else:
                    try:
                        # 转换为 Base64 格式
                        with open(image, "rb") as f:
                            image_base64 = base64.b64encode(f.read()).decode("ascii")
                        data["image"] = image_base64
                    except Exception as e:
                        return {"error": f"Image encoding failed: {str(e)}"}

            response = requests.post(
                f"{base_url}/generate",
                json = data,
            )

            if response.status_code != 200:
                return {
                    "error": f"Generation failed: {response.text}"
                }
        
            # 解码 base64 并保存到临时文件
            with tempfile.NamedTemporaryFile(delete=False, suffix=".glb") as temp_file:
                temp_file.write(response.content)
                temp_file_name = temp_file.name

            # 在主线程中导入 GLB 文件
            def import_handler():
                bpy.ops.import_scene.gltf(filepath=temp_file_name)
                os.unlink(temp_file.name)
                return None
            
            bpy.app.timers.register(import_handler)

            return {
                "status": "DONE",
                "message": "生成并导入 GLB 成功"
            }
        except Exception as e:
            print(f"发生错误：{e}")
            return {"error": str(e)}
        
    
    def poll_hunyuan_job_status(self, *args, **kwargs):
        return self.poll_hunyuan_job_status_ai(*args, **kwargs)
    
    def poll_hunyuan_job_status_ai(self, job_id: str):
        """调用任务状态 API 获取任务状态"""
        print(job_id)
        try:
            secret_id = self._get_hunyuan3d_secret_id()
            secret_key = self._get_hunyuan3d_secret_key()

            if not secret_id or not secret_key:
                return {"error": "未提供 SecretId 或 SecretKey"}
            if not job_id:
                return {"error": "需要提供 JobId"}
            
            service = "hunyuan"
            action = "QueryHunyuanTo3DJob"
            version = "2023-09-01"
            region = "ap-guangzhou"

            headParams={
                "Action": action,
                "Version": version,
                "Region": region,
            }

            clean_job_id = job_id.removeprefix("job_")
            data = {
                "JobId": clean_job_id
            }

            headers, endpoint = self.get_tencent_cloud_sign_headers("POST", "/", headParams, data, service, region, secret_id, secret_key)

            response = requests.post(
                endpoint,
                headers=headers,
                data=json.dumps(data)
            )

            if response.status_code == 200:
                return response.json()
            return {
                "error": f"API 请求失败，状态码 {response.status_code}：{response}"
            }
        except Exception as e:
            return {"error": str(e)}

    def import_generated_asset_hunyuan(self, *args, **kwargs):
        return self.import_generated_asset_hunyuan_ai(*args, **kwargs)
            
    def import_generated_asset_hunyuan_ai(self, name: str , zip_file_url: str):
        if not zip_file_url:
            return {"error": "未找到 ZIP 文件"}
        
        # 验证 URL
        if not re.match(r'^https?://', zip_file_url, re.IGNORECASE):
            return {"error": "URL 格式无效。必须以 http:// 或 https:// 开头"}
        
        # 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix="tencent_obj_")
        zip_file_path = osp.join(temp_dir, "model.zip")
        obj_file_path = osp.join(temp_dir, "model.obj")
        mtl_file_path = osp.join(temp_dir, "model.mtl")

        try:
            # 下载 ZIP 文件
            zip_response = requests.get(zip_file_url, stream=True)
            zip_response.raise_for_status()
            with open(zip_file_path, "wb") as f:
                for chunk in zip_response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 解压 ZIP 文件
            with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            # 查找 .obj 文件（可能有多个，假设主文件为 model.obj）
            for file in os.listdir(temp_dir):
                if file.endswith(".obj"):
                    obj_file_path = osp.join(temp_dir, file)

            if not osp.exists(obj_file_path):
                return {"succeed": False, "error": "解压后未找到 OBJ 文件"}

            # 导入 obj 文件
            if bpy.app.version>=(4, 0, 0):
                bpy.ops.wm.obj_import(filepath=obj_file_path)
            else:
                bpy.ops.import_scene.obj(filepath=obj_file_path)

            imported_objs = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
            if not imported_objs:
                return {"succeed": False, "error": "未导入任何网格对象"}

            obj = imported_objs[0]
            if name:
                obj.name = name

            result = {
                "name": obj.name,
                "type": obj.type,
                "location": [obj.location.x, obj.location.y, obj.location.z],
                "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
                "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            }

            if obj.type == "MESH":
                bounding_box = self._get_aabb(obj)
                result["world_bounding_box"] = bounding_box

            return {"succeed": True, **result}
        except Exception as e:
            return {"succeed": False, "error": str(e)}
        finally:
            # 清理临时 zip 和 obj 文件，保留纹理和 mtl
            try:
                if os.path.exists(zip_file_path):
                    os.remove(zip_file_path) 
                if os.path.exists(obj_file_path):
                    os.remove(obj_file_path)
            except Exception as e:
                print(f"清理临时目录失败 {temp_dir}：{e}")
    #endregion

# Blender 插件首选项
class BLENDERMCP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    
    telemetry_consent: BoolProperty(
        name="允许遥测",
        description="允许收集提示词、代码片段和截图以帮助改进 Blender MCP",
        default=False
    )
    hyper3d_api_key: bpy.props.StringProperty(
        name="Hyper3D API 密钥",
        subtype="PASSWORD",
        description="持久化 Hyper3D API 密钥",
        default=""
    )
    sketchfab_api_key: bpy.props.StringProperty(
        name="Sketchfab API 密钥",
        subtype="PASSWORD",
        description="持久化 Sketchfab API 密钥",
        default=""
    )
    hunyuan3d_secret_id: bpy.props.StringProperty(
        name="Hunyuan3D SecretId",
        description="持久化 Hunyuan3D SecretId",
        default=""
    )
    hunyuan3d_secret_key: bpy.props.StringProperty(
        name="Hunyuan3D SecretKey",
        subtype="PASSWORD",
        description="持久化 Hunyuan3D SecretKey",
        default=""
    )
    hunyuan3d_api_url: bpy.props.StringProperty(
        name="Hunyuan3D API 地址",
        description="持久化 Hunyuan3D API 地址",
        default=""
    )

    def draw(self, context):
        layout = self.layout
        
        # 遥测部分
        layout.label(text="遥测与隐私：", icon='PREFERENCES')
        
        box = layout.box()
        row = box.row()
        row.prop(self, "telemetry_consent", text="允许遥测")
        
        # 信息文本
        box.separator()
        if self.telemetry_consent:
            box.label(text="已同意：我们收集匿名化的提示词、代码和截图。", icon='INFO')
        else:
            box.label(text="未同意：我们仅收集最少的匿名使用数据", icon='INFO')
            box.label(text="（工具名称、成功/失败、耗时 - 不含提示词或代码）。", icon='BLANK1')
        box.separator()
        box.label(text="所有数据完全匿名化。您可以随时更改此设置。", icon='CHECKMARK')
        
        # 条款链接
        box.separator()
        row = box.row()
        row.operator("blendermcp.open_terms", text="查看使用条款", icon='TEXT')

        layout.separator()
        layout.label(text="持久化 API 凭据：", icon='LOCKED')
        cred_box = layout.box()
        cred_box.prop(self, "sketchfab_api_key", text="Sketchfab API 密钥")
        cred_box.prop(self, "hyper3d_api_key", text="Hyper3D API 密钥")
        cred_box.prop(self, "hunyuan3d_secret_id", text="Hunyuan3D SecretId")
        cred_box.prop(self, "hunyuan3d_secret_key", text="Hunyuan3D SecretKey")
        cred_box.prop(self, "hunyuan3d_api_url", text="Hunyuan3D API 地址")

# Blender UI 面板
class BLENDERMCP_PT_Panel(bpy.types.Panel):
    bl_label = "Blender MCP"
    bl_idname = "BLENDERMCP_PT_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderMCP'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        prefs = get_blendermcp_addon_preferences(context)

        layout.prop(scene, "blendermcp_port")
        layout.prop(scene, "blendermcp_use_polyhaven", text="使用 Poly Haven 资产")

        layout.prop(scene, "blendermcp_use_hyper3d", text="使用 Hyper3D Rodin 3D 模型生成")
        if scene.blendermcp_use_hyper3d:
            layout.prop(scene, "blendermcp_hyper3d_mode", text="Rodin 模式")
            if prefs:
                layout.prop(prefs, "hyper3d_api_key", text="API 密钥")
            else:
                layout.prop(scene, "blendermcp_hyper3d_api_key", text="API 密钥")
            layout.operator("blendermcp.set_hyper3d_free_trial_api_key", text="设置免费试用 API 密钥")

        layout.prop(scene, "blendermcp_use_sketchfab", text="使用 Sketchfab 资产")
        if scene.blendermcp_use_sketchfab:
            if prefs:
                layout.prop(prefs, "sketchfab_api_key", text="API 密钥")
            else:
                layout.prop(scene, "blendermcp_sketchfab_api_key", text="API 密钥")

        layout.prop(scene, "blendermcp_use_hunyuan3d", text="使用腾讯混元 3D 模型生成")
        if scene.blendermcp_use_hunyuan3d:
            layout.prop(scene, "blendermcp_hunyuan3d_mode", text="混元3D 模式")
            if scene.blendermcp_hunyuan3d_mode == 'OFFICIAL_API':
                if prefs:
                    layout.prop(prefs, "hunyuan3d_secret_id", text="SecretId")
                    layout.prop(prefs, "hunyuan3d_secret_key", text="SecretKey")
                else:
                    layout.prop(scene, "blendermcp_hunyuan3d_secret_id", text="SecretId")
                    layout.prop(scene, "blendermcp_hunyuan3d_secret_key", text="SecretKey")
            if scene.blendermcp_hunyuan3d_mode == 'LOCAL_API':
                if prefs:
                    layout.prop(prefs, "hunyuan3d_api_url", text="API 地址")
                else:
                    layout.prop(scene, "blendermcp_hunyuan3d_api_url", text="API 地址")
                layout.prop(scene, "blendermcp_hunyuan3d_octree_resolution", text="八叉树分辨率")
                layout.prop(scene, "blendermcp_hunyuan3d_num_inference_steps", text="推理步数")
                layout.prop(scene, "blendermcp_hunyuan3d_guidance_scale", text="引导强度")
                layout.prop(scene, "blendermcp_hunyuan3d_texture", text="生成纹理")
        
        if not scene.blendermcp_server_running:
            layout.operator("blendermcp.start_server", text="连接 MCP 服务器")
        else:
            layout.operator("blendermcp.stop_server", text="断开 MCP 服务器连接")
            layout.label(text=f"正在端口 {scene.blendermcp_port} 上运行")
        
        # 反馈部分
        layout.separator()
        feedback_box = layout.box()
        
        col = feedback_box.column(align=True)
        col.label(text="反馈", icon='URL')
        col.label(text="bit.ly/blender-mcp-form")
        col.separator()
        col.label(text="预约通话", icon='URL')
        col.label(text="bit.ly/blender-mcp-call")
        col.label(text="（我们会在仓库中注明您的贡献！）")

# 设置 Hyper3D API 密钥的操作符
class BLENDERMCP_OT_SetFreeTrialHyper3DAPIKey(bpy.types.Operator):
    bl_idname = "blendermcp.set_hyper3d_free_trial_api_key"
    bl_label = "设置免费试用 API 密钥"

    def execute(self, context):
        prefs = get_blendermcp_addon_preferences(context)
        if prefs:
            if not prefs.hyper3d_api_key or prefs.hyper3d_api_key == RODIN_FREE_TRIAL_KEY:
                prefs.hyper3d_api_key = RODIN_FREE_TRIAL_KEY
            else:
                self.report(
                    {'INFO'},
                    "本次会话使用免费试用；已保存的私钥已保留。"
                )
        context.scene.blendermcp_hyper3d_api_key = RODIN_FREE_TRIAL_KEY
        context.scene.blendermcp_hyper3d_mode = 'MAIN_SITE'
        self.report({'INFO'}, "API 密钥设置成功！")
        return {'FINISHED'}

# 启动服务器的操作符
class BLENDERMCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "连接到 Claude"
    bl_description = "启动 BlenderMCP 服务器以连接 Claude"

    def execute(self, context):
        scene = context.scene

        # 创建新的服务器实例
        if not hasattr(bpy.types, "blendermcp_server") or not bpy.types.blendermcp_server:
            bpy.types.blendermcp_server = BlenderMCPServer(port=scene.blendermcp_port)

        # 启动服务器
        bpy.types.blendermcp_server.start()
        scene.blendermcp_server_running = bpy.types.blendermcp_server.running

        return {'FINISHED'}

# 停止服务器的操作符
class BLENDERMCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "断开与 Claude 的连接"
    bl_description = "断开与 Claude 的连接"

    def execute(self, context):
        scene = context.scene

        # 停止服务器（如果存在）
        if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server:
            bpy.types.blendermcp_server.stop()
            del bpy.types.blendermcp_server

        scene.blendermcp_server_running = False

        return {'FINISHED'}

# 打开使用条款的操作符
class BLENDERMCP_OT_OpenTerms(bpy.types.Operator):
    bl_idname = "blendermcp.open_terms"
    bl_label = "查看使用条款"
    bl_description = "打开使用条款文档"

    def execute(self, context):
        # 在浏览器中打开使用条款
        terms_url = "https://github.com/ahujasid/blender-mcp/blob/main/TERMS_AND_CONDITIONS.md"
        try:
            import webbrowser
            webbrowser.open(terms_url)
            self.report({'INFO'}, "已在浏览器中打开使用条款")
        except Exception as e:
            self.report({'ERROR'}, f"无法打开使用条款：{str(e)}")
        
        return {'FINISHED'}

# 注册函数
def register():
    bpy.types.Scene.blendermcp_port = IntProperty(
        name="端口",
        description="BlenderMCP 服务器端口",
        default=9876,
        min=1024,
        max=65535
    )

    bpy.types.Scene.blendermcp_server_running = bpy.props.BoolProperty(
        name="服务器运行中",
        default=False
    )

    bpy.types.Scene.blendermcp_auto_start_server = bpy.props.BoolProperty(
        name="自动启动服务器",
        description="Blender 加载时自动启动 MCP 服务器",
        default=True
    )

    bpy.types.Scene.blendermcp_use_polyhaven = bpy.props.BoolProperty(
        name="使用 Poly Haven",
        description="启用 Poly Haven 资产集成",
        default=False
    )

    bpy.types.Scene.blendermcp_use_hyper3d = bpy.props.BoolProperty(
        name="使用 Hyper3D Rodin",
        description="启用 Hyper3D Rodin 生成集成",
        default=False
    )

    bpy.types.Scene.blendermcp_hyper3d_mode = bpy.props.EnumProperty(
        name="Rodin 模式",
        description="选择调用 Rodin API 的平台",
        items=[
            ("MAIN_SITE", "hyper3d.ai", "hyper3d.ai"),
            ("FAL_AI", "fal.ai", "fal.ai"),
        ],
        default="MAIN_SITE"
    )

    bpy.types.Scene.blendermcp_hyper3d_api_key = bpy.props.StringProperty(
        name="Hyper3D API 密钥",
        subtype="PASSWORD",
        description="Hyper3D 提供的 API 密钥",
        default=""
    )

    bpy.types.Scene.blendermcp_use_hunyuan3d = bpy.props.BoolProperty(
        name="使用混元 3D",
        description="启用混元资产集成",
        default=False
    )

    bpy.types.Scene.blendermcp_hunyuan3d_mode = bpy.props.EnumProperty(
        name="混元3D 模式",
        description="选择本地或官方 API",
        items=[
            ("LOCAL_API", "本地 API", "本地 API"),
            ("OFFICIAL_API", "官方 API", "官方 API"),
        ],
        default="LOCAL_API"
    )

    bpy.types.Scene.blendermcp_hunyuan3d_secret_id = bpy.props.StringProperty(
        name="混元 3D SecretId",
        description="混元 3D 提供的 SecretId",
        default=""
    )

    bpy.types.Scene.blendermcp_hunyuan3d_secret_key = bpy.props.StringProperty(
        name="混元 3D SecretKey",
        subtype="PASSWORD",
        description="混元 3D 提供的 SecretKey",
        default=""
    )

    bpy.types.Scene.blendermcp_hunyuan3d_api_url = bpy.props.StringProperty(
        name="API 地址",
        description="混元 3D API 服务地址",
        default="http://localhost:8081"
    )

    bpy.types.Scene.blendermcp_hunyuan3d_octree_resolution = bpy.props.IntProperty(
        name="八叉树分辨率",
        description="3D 生成的八叉树分辨率",
        default=256,
        min=128,
        max=512,
    )

    bpy.types.Scene.blendermcp_hunyuan3d_num_inference_steps = bpy.props.IntProperty(
        name="推理步数",
        description="3D 生成的推理步数",
        default=20,
        min=20,
        max=50,
    )

    bpy.types.Scene.blendermcp_hunyuan3d_guidance_scale = bpy.props.FloatProperty(
        name="引导强度",
        description="3D 生成的引导强度",
        default=5.5,
        min=1.0,
        max=10.0,
    )

    bpy.types.Scene.blendermcp_hunyuan3d_texture = bpy.props.BoolProperty(
        name="生成纹理",
        description="是否为 3D 模型生成纹理",
        default=False,
    )
    
    bpy.types.Scene.blendermcp_use_sketchfab = bpy.props.BoolProperty(
        name="使用 Sketchfab",
        description="启用 Sketchfab 资产集成",
        default=False
    )

    bpy.types.Scene.blendermcp_sketchfab_api_key = bpy.props.StringProperty(
        name="Sketchfab API 密钥",
        subtype="PASSWORD",
        description="Sketchfab 提供的 API 密钥",
        default=""
    )

    # 注册首选项类
    bpy.utils.register_class(BLENDERMCP_AddonPreferences)

    bpy.utils.register_class(BLENDERMCP_PT_Panel)
    bpy.utils.register_class(BLENDERMCP_OT_SetFreeTrialHyper3DAPIKey)
    bpy.utils.register_class(BLENDERMCP_OT_StartServer)
    bpy.utils.register_class(BLENDERMCP_OT_StopServer)
    bpy.utils.register_class(BLENDERMCP_OT_OpenTerms)

    # 自动启动服务器，以便 MCP 客户端无需手动 UI 交互即可连接
    scene = getattr(bpy.context, 'scene', None)
    if scene is not None:
        port = scene.blendermcp_port
        auto_start = scene.blendermcp_auto_start_server
    else:
        port = 9876
        auto_start = True

    if auto_start and (not hasattr(bpy.types, "blendermcp_server") or not bpy.types.blendermcp_server):
        bpy.types.blendermcp_server = BlenderMCPServer(port=port)
    if auto_start and not bpy.types.blendermcp_server.running:
        bpy.types.blendermcp_server.start()
        try:
            bpy.context.scene.blendermcp_server_running = bpy.types.blendermcp_server.running
        except AttributeError:
            pass

    print("BlenderMCP 插件已注册")

def unregister():
    # 如果服务器正在运行则停止它
    if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server:
        bpy.types.blendermcp_server.stop()
        del bpy.types.blendermcp_server

    bpy.utils.unregister_class(BLENDERMCP_PT_Panel)
    bpy.utils.unregister_class(BLENDERMCP_OT_SetFreeTrialHyper3DAPIKey)
    bpy.utils.unregister_class(BLENDERMCP_OT_StartServer)
    bpy.utils.unregister_class(BLENDERMCP_OT_StopServer)
    bpy.utils.unregister_class(BLENDERMCP_OT_OpenTerms)
    bpy.utils.unregister_class(BLENDERMCP_AddonPreferences)

    del bpy.types.Scene.blendermcp_port
    del bpy.types.Scene.blendermcp_server_running
    del bpy.types.Scene.blendermcp_auto_start_server
    del bpy.types.Scene.blendermcp_use_polyhaven
    del bpy.types.Scene.blendermcp_use_hyper3d
    del bpy.types.Scene.blendermcp_hyper3d_mode
    del bpy.types.Scene.blendermcp_hyper3d_api_key
    del bpy.types.Scene.blendermcp_use_sketchfab
    del bpy.types.Scene.blendermcp_sketchfab_api_key
    del bpy.types.Scene.blendermcp_use_hunyuan3d
    del bpy.types.Scene.blendermcp_hunyuan3d_mode
    del bpy.types.Scene.blendermcp_hunyuan3d_secret_id
    del bpy.types.Scene.blendermcp_hunyuan3d_secret_key
    del bpy.types.Scene.blendermcp_hunyuan3d_api_url
    del bpy.types.Scene.blendermcp_hunyuan3d_octree_resolution
    del bpy.types.Scene.blendermcp_hunyuan3d_num_inference_steps
    del bpy.types.Scene.blendermcp_hunyuan3d_guidance_scale
    del bpy.types.Scene.blendermcp_hunyuan3d_texture

    print("BlenderMCP 插件已注销")

if __name__ == "__main__":
    register()
