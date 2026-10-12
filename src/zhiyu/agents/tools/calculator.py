"""安全的数学计算工具（AST 白名单解析，禁 eval）。"""

import ast
import operator

from .base import AgentTool

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}


class CalculatorTool(AgentTool):
    name = "calculator"
    description = "计算一个数学表达式（四则运算、幂、取模），返回数值结果。"
    schema = {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 '2 + 3 * 4'"},
        },
        "required": ["expression"],
    }

    async def execute(self, expression: str) -> int | float:
        return self._eval(expression)

    @staticmethod
    def _eval(expression: str) -> int | float:
        tree = ast.parse(expression, mode="eval")
        return CalculatorTool._eval_node(tree.body)

    @staticmethod
    def _eval_node(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return CalculatorTool._eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](
                CalculatorTool._eval_node(node.left),
                CalculatorTool._eval_node(node.right),
            )
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
            return CalculatorTool._eval_node(node.operand)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -CalculatorTool._eval_node(node.operand)
        raise ValueError(f"不支持的表达式: {ast.dump(node)}")
