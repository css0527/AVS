"""Small YOLOv5 detection network used for the five course pictograms.

The model keeps the characteristic YOLOv5 C3/SPPF backbone, PAN neck and
three anchor heads.  Training lives in tools/train_yolov5_hazards.py; runtime
loads the exported TorchScript artifact and does not need the training code.
"""
import torch
from torch import nn


class Conv(nn.Module):
    def __init__(self, c1, c2, k=1, s=1, p=None):
        super().__init__()
        self.conv = nn.Conv2d(c1, c2, k, s, k // 2 if p is None else p, bias=False)
        self.bn = nn.BatchNorm2d(c2)
        self.act = nn.SiLU(inplace=True)

    def forward(self, x):
        return self.act(self.bn(self.conv(x)))


class Bottleneck(nn.Module):
    def __init__(self, channels, shortcut=True):
        super().__init__()
        hidden = channels // 2
        self.cv1 = Conv(channels, hidden, 1)
        self.cv2 = Conv(hidden, channels, 3)
        self.shortcut = shortcut

    def forward(self, x):
        y = self.cv2(self.cv1(x))
        return x + y if self.shortcut else y


class C3(nn.Module):
    def __init__(self, c1, c2, repeats=1):
        super().__init__()
        hidden = c2 // 2
        self.cv1 = Conv(c1, hidden, 1)
        self.cv2 = Conv(c1, hidden, 1)
        self.blocks = nn.Sequential(*(Bottleneck(hidden) for _ in range(repeats)))
        self.cv3 = Conv(hidden * 2, c2, 1)

    def forward(self, x):
        return self.cv3(torch.cat((self.blocks(self.cv1(x)), self.cv2(x)), 1))


class SPPF(nn.Module):
    def __init__(self, c1, c2):
        super().__init__()
        hidden = c1 // 2
        self.cv1 = Conv(c1, hidden, 1)
        self.cv2 = Conv(hidden * 4, c2, 1)
        self.pool = nn.MaxPool2d(5, 1, 2)

    def forward(self, x):
        x = self.cv1(x)
        y1 = self.pool(x)
        y2 = self.pool(y1)
        return self.cv2(torch.cat((x, y1, y2, self.pool(y2)), 1))


class YoloV5HazardNet(nn.Module):
    """Compact five-class YOLOv5 model, suitable for CPU simulation."""
    def __init__(self, classes=5, width=16):
        super().__init__()
        c1, c2, c3, c4, c5 = width, width * 2, width * 4, width * 8, width * 16
        self.stem = Conv(3, c1, 6, 2, 2)
        self.down2, self.c3_2 = Conv(c1, c2, 3, 2), C3(c2, c2, 1)
        self.down3, self.c3_3 = Conv(c2, c3, 3, 2), C3(c3, c3, 2)
        self.down4, self.c3_4 = Conv(c3, c4, 3, 2), C3(c4, c4, 2)
        self.down5 = Conv(c4, c5, 3, 2)
        self.c3_5, self.sppf = C3(c5, c5, 1), SPPF(c5, c5)

        self.reduce5 = Conv(c5, c4, 1)
        self.neck4 = C3(c4 + c4, c4, 1)
        self.reduce4 = Conv(c4, c3, 1)
        self.neck3 = C3(c3 + c3, c3, 1)
        self.down_neck4 = Conv(c3, c3, 3, 2)
        self.out4 = C3(c3 + c4, c4, 1)
        self.down_neck5 = Conv(c4, c4, 3, 2)
        self.out5 = C3(c4 + c5, c5, 1)
        outputs = 3 * (classes + 5)
        self.detect3 = nn.Conv2d(c3, outputs, 1)
        self.detect4 = nn.Conv2d(c4, outputs, 1)
        self.detect5 = nn.Conv2d(c5, outputs, 1)
        self.classes = classes
        self.register_buffer('anchors', torch.tensor([
            [[10., 13.], [16., 30.], [33., 23.]],
            [[30., 61.], [62., 45.], [59., 119.]],
            [[116., 90.], [156., 198.], [373., 326.]],
        ]) / 640.)
        self._initialize_biases()

    def _initialize_biases(self):
        # A sparse detector should not begin with 0.5 object confidence at
        # every grid cell.  These priors stabilize training from scratch.
        for layer in (self.detect3, self.detect4, self.detect5):
            bias = layer.bias.detach().view(3, self.classes + 5)
            bias[:, 4] = -4.5
            bias[:, 5:] = -2.0
            layer.bias = nn.Parameter(bias.reshape(-1), requires_grad=True)

    def features(self, x):
        x = self.stem(x)
        x = self.c3_2(self.down2(x))
        p3 = self.c3_3(self.down3(x))
        p4 = self.c3_4(self.down4(p3))
        p5 = self.sppf(self.c3_5(self.down5(p4)))
        n4 = self.neck4(torch.cat((nn.functional.interpolate(self.reduce5(p5),
                              scale_factor=2., mode='nearest'), p4), 1))
        n3 = self.neck3(torch.cat((nn.functional.interpolate(self.reduce4(n4),
                              scale_factor=2., mode='nearest'), p3), 1))
        o4 = self.out4(torch.cat((self.down_neck4(n3), n4), 1))
        o5 = self.out5(torch.cat((self.down_neck5(o4), p5), 1))
        return n3, o4, o5

    def forward_raw(self, x):
        n3, o4, o5 = self.features(x)
        maps = (self.detect3(n3), self.detect4(o4), self.detect5(o5))
        result = []
        for output in maps:
            b, _, h, w = output.shape
            result.append(output.view(b, 3, self.classes + 5, h, w).permute(0, 1, 3, 4, 2))
        return result

    @staticmethod
    def decode_scale(raw, anchors):
        _, _, h, w, _ = raw.shape
        y, x = torch.meshgrid(torch.arange(h, device=raw.device),
                              torch.arange(w, device=raw.device), indexing='ij')
        grid = torch.stack((x, y), -1).to(raw.dtype).view(1, 1, h, w, 2)
        scale = torch.tensor([w, h], device=raw.device, dtype=raw.dtype)
        xy = (raw[..., 0:2].sigmoid() * 2. - .5 + grid) / scale
        wh = (raw[..., 2:4].sigmoid() * 2.) ** 2 * anchors.view(1, 3, 1, 1, 2)
        scores = raw[..., 4:].sigmoid()
        return torch.cat((xy, wh, scores), -1).view(raw.shape[0], -1, raw.shape[-1])

    def forward(self, x):
        raw = self.forward_raw(x)
        return torch.cat(tuple(self.decode_scale(value, self.anchors[index])
                               for index, value in enumerate(raw)), 1)
