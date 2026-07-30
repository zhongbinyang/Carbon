# 4通道光模块温控测试机台架构说明

根据测试机台的实物照片 [001.jpg](file:///C:/Users/zhong/git/Carbon/photo/001.jpg)、[002.jpg](file:///C:/Users/zhong/git/Carbon/photo/002.jpg) 以及型号清单 [003.txt](file:///C:/Users/zhong/git/Carbon/photo/003.txt)，该测试机台是一台**4通道光模块温控测试机台**。

---

## 1. 系统架构图

```mermaid
graph TD
    %% 颜色定义
    classDef power fill:#f96,stroke:#333,stroke-width:2px;
    classDef control fill:#6cf,stroke:#333,stroke-width:2px;
    classDef temp fill:#ff9,stroke:#333,stroke-width:2px;
    classDef test fill:#9f9,stroke:#333,stroke-width:2px;

    %% 供电系统
    subgraph PowerSystem ["供电与配电系统 (Power & Distribution)"]
        AC[220V AC 输入] --> Breaker[NXBLE-32 漏电断路器]
        Breaker --> PS1[LRS-600-24 开关电源 1]
        Breaker --> PS2[LRS-600-24 开关电源 2]
        PS1 --> Bus24V[24V DC 总线 / 端子排]
        PS2 --> Bus24V
    end

    %% 主控制系统
    subgraph ControlSystem ["主控制与通信系统 (Control & Comm)"]
        PC[上位机 Host PC] -->|USB| USB_Hub1[JTT1005 通信板 1]
        PC -->|USB| USB_Hub2[JTT1005 通信板 2]
        
        USB_Hub1 --> MainCtrl[JTT1051 主控/总线板]
        USB_Hub2 --> IO_Board[JTT1047V2 I/O板 *2]
        
        IO_Board --> Relay[HF3FF 继电器板]
        MainCtrl -->|"RS485/CAN 总线"| TCB_NE
    end

    %% 显示与辅助
    JTT1049[JTT1049V3 状态显示/电源开关板]

    %% 温控与测试工位 (4通道)
    subgraph TestChannels ["4通道独立测试工位 (Test Slots * 4)"]
        TCB_NE[TCB-NE 温控板 *4]
        
        %% 通道 1
        subgraph CH1 [通道 1]
            T1[TCB-NE 1] --> TEC1[TEC 制冷器 1]
            T1 --> Fan1[散热风扇 1]
            Slot1[JTT1031V3 测试板 1]
        end

        %% 通道 2
        subgraph CH2 [通道 2]
            T2[TCB-NE 2] --> TEC2[TEC 制冷器 2]
            T2 --> Fan2[散热风扇 2]
            Slot2[JTT1031V3 测试板 2]
        end

        %% 通道 3
        subgraph CH3 [通道 3]
            T3[TCB-NE 3] --> TEC3[TEC 制冷器 3]
            T3 --> Fan3[散热风扇 3]
            Slot3[JTT1031V3 测试板 3]
        end

        %% 通道 4
        subgraph CH4 [通道 4]
            T4[TCB-NE 4] --> TEC4[TEC 制冷器 4]
            T4 --> Fan4[散热风扇 4]
            Slot4[JTT1031V3 测试板 4]
        end
    end

    %% 连线关系
    Bus24V ==> JTT1049
    Bus24V ==> TCB_NE
    Bus24V ==> MainCtrl
    Bus24V ==> IO_Board
    Bus24V ==> Slot1 & Slot2 & Slot3 & Slot4
    
    Relay -. "控制通道电源" .-> Slot1
    Relay -. "控制通道电源" .-> Slot2
    Relay -. "控制通道电源" .-> Slot3
    Relay -. "控制通道电源" .-> Slot4

    %% 样式应用
    class AC,Breaker,PS1,PS2,Bus24V power;
    class PC,USB_Hub1,USB_Hub2,MainCtrl,IO_Board,JTT1049,Relay control;
    class TCB_NE,T1,T2,T3,T4 temp;
    class Slot1,Slot2,Slot3,Slot4,TEC1,TEC2,TEC3,TEC4,Fan1,Fan2,Fan3,Fan4,CH1,CH2,CH3,CH4 test;
```

---

## 2. 系统模块功能说明

根据硬件配置，整个机台分为四大系统：

### 2.1 电源与配电系统
* **[NXBLE-32](file:///C:/Users/zhong/git/Carbon/photo/003.txt#L1)** (漏电断路器)：起整机交流电（AC）的过载、短路及漏电保护作用。
* **[LRS-600-24 * 2](file:///C:/Users/zhong/git/Carbon/photo/003.txt#L2)** (明纬 24V 开关电源)：提供整机直流（DC）供电，单路最大功率 600W，保障温控 TEC 满载制冷/加热时的电量需求。
* **接线端子排**：分流 24V DC 总线电源至各控制板卡和测试工位。

### 2.2 主控制与信号路切换
* **[JTT1005 * 2](file:///C:/Users/zhong/git/Carbon/photo/003.txt#L7)**：USB 接口转串口通信板，作为上位机 PC 与各个 JTT 模块之间的高速通信网关。
* **[JTT1051](file:///C:/Users/zhong/git/Carbon/photo/003.txt#L9)** & **[JTT1047V2 * 2](file:///C:/Users/zhong/git/Carbon/photo/003.txt#L8)**：主控制板和 I/O 拓展板，用于收集通道状态，并控制开关信号。
* **[HF3FF](file:///C:/Users/zhong/git/Carbon/photo/003.txt#L4)** (宏发继电器板)：用于切断或使能每个通道的供电、复位等硬控制线。
* **[JTT1049V3](file:///C:/Users/zhong/git/Carbon/photo/003.txt#L3)**：位于面板左上角，配有 LED 数码管和 4 个红色船型开关，用于各测试通道电源的手动切换与状态直观显示。

### 2.3 精准温控系统
* **[TCB-NE * 4](file:///C:/Users/zhong/git/Carbon/photo/003.txt#L5)** (TEC 温控驱动板)：
  * 针对 4 个测试通道进行独立温控。
  * 根据设定的温度（如常规测试的 $0\sim 70^\circ\text{C}$），通过双向 H 桥驱动 **TEC（半导体制冷片）** 实现快速加热或制冷。
  * 采集每个测试夹具内部的温度传感器反馈，进行闭环 PID 调节。

### 2.4 测试通道与夹具
* 机台顶部共有 4 个独立的测试工位，每个工位配备一块 **[JTT1031V3](file:///C:/Users/zhong/git/Carbon/photo/003.txt#L11)** 测试接口板（光模块插槽及外围电路）。
* 每个工位下方紧贴 TEC 制冷片、散热片及 **防反转散热风扇**（用于 TEC 热端散热）。
* 配有光纤软管将光信号引出至光功率计/误码仪等检测仪表。
