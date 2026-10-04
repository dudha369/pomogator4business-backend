import ast
import operator

from core.context import CommandContext
from core.registry import command

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_MAX_POWER_EXPONENT = 1000


class CalcError(Exception):
    pass


def _eval_node(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise CalcError("bad constant")

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _OPS:
            raise CalcError("bad operator")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if op_type is ast.Pow and abs(right) > _MAX_POWER_EXPONENT:
            raise CalcError("exponent too large")
        return _OPS[op_type](left, right)

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _OPS:
            raise CalcError("bad operator")
        return _OPS[op_type](_eval_node(node.operand))

    raise CalcError("unsupported expression")


def safe_eval(expression):
    tree = ast.parse(expression, mode="eval")
    return _eval_node(tree.body)


@command(name="calc", module="calc")
async def cmd_calc(ctx: CommandContext):
    expression = ctx.args.strip()
    if not expression:
        await ctx.usage_error(ctx.t("calc.usage"))
        return

    try:
        result = safe_eval(expression)
    except (CalcError, SyntaxError, ZeroDivisionError, OverflowError, ValueError):
        await ctx.reply(ctx.t("calc.error"))
        return

    if isinstance(result, float) and result.is_integer():
        result = int(result)

    await ctx.reply(f"{expression} = {result}")
