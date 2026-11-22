from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "owner_keys" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "owner_id" BIGINT NOT NULL,
    "version" SMALLINT NOT NULL,
    "wrapped_dek" BYTEA NOT NULL,
    "master_version" SMALLINT NOT NULL,
    "created_at" BIGINT NOT NULL,
    CONSTRAINT "uid_owner_keys_owner_i_c92b91" UNIQUE ("owner_id", "version")
);
COMMENT ON TABLE "owner_keys" IS 'Ключ данных владельца, обёрнутый мастер-ключом. Активная — наибольшая версия;';
        ALTER TABLE "ai_drafts" ADD "enc_ver" SMALLINT;
        ALTER TABLE "message_history" ADD "enc_ver" SMALLINT;
        ALTER TABLE "message_history" ALTER COLUMN "media_name" TYPE TEXT USING "media_name"::TEXT;
        ALTER TABLE "archive_log" ADD "enc_ver" SMALLINT;
        ALTER TABLE "archive_log" ALTER COLUMN "media_name" TYPE TEXT USING "media_name"::TEXT;
        ALTER TABLE "scheduled_tasks" ADD "enc_ver" SMALLINT;
        ALTER TABLE "alerts" ADD "enc_ver" SMALLINT;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "alerts" DROP COLUMN "enc_ver";
        ALTER TABLE "ai_drafts" DROP COLUMN "enc_ver";
        ALTER TABLE "archive_log" DROP COLUMN "enc_ver";
        ALTER TABLE "archive_log" ALTER COLUMN "media_name" TYPE VARCHAR(255) USING "media_name"::VARCHAR(255);
        ALTER TABLE "scheduled_tasks" DROP COLUMN "enc_ver";
        ALTER TABLE "message_history" DROP COLUMN "enc_ver";
        ALTER TABLE "message_history" ALTER COLUMN "media_name" TYPE VARCHAR(255) USING "media_name"::VARCHAR(255);
        DROP TABLE IF EXISTS "owner_keys";"""


MODELS_STATE = (
    "eJztXW13m7i2/issf0rW9aR+wYnTe+eslbSZmZ5p2rlN5twzZzqLYJATJhg8gNPmnNX/fh"
    "ESsIUkghzbgURf3Aa0QTwI6dmv+k9vEbrIjw/ehEGAnMQLg95r4z+9wF6g9D+Cs32jZy+X"
    "5Tl8ILFnftbcKdplx+1ZnES2k6Sn5rYfo/SQi2In8pb0RsHK9/HB0EkbesF1eWgVeH+tkJ"
    "WE1yi5QVF64vc/0sNe4KKvKM7/XN5acw/5LtPnshOW5+JuZE2s5H6ZnX5zY0c/ZEL4zjPL"
    "Cf3VIhAKLu+Tm/SPXDLtIz56jQIU2QlywWPhXlMQ8kPkCdIDSbRCRdfd8oCL5vbKTwAMDb"
    "FJ+4lx9YIkzh58YX+1fBRcJzfpn6PJ5Bt5sPKxSTP8CP84+fTmp5NPe2mrffwsYfp6yKv7"
    "QE+NyLlv2UXsxCaXyRAvIQ6/pBAI0T31rt8FiRhfKFWBNn2WdaDND5TYluNsQ+Be4/t8dz"
    "wajcdHo8H4cDoxj44m08E0bZt1ij91VPMCTt/9+O7DJQs9PoDxruLr3NjJmiADUY30w0hn"
    "fynMFKzUWtMEnQR2CfC25okqmqsYReshCiU1qjmqXmyhAD+gaCoIQx/ZgRhUVrAC6CyV3N"
    "ZMUKxwa0Fa91F//Pged3oRx3/55CuvfOIffj0/Pfu0N8wATht5ieTLX0Zo7n1VGaOlxGaI"
    "QRMkewe9TY3NaYOROZWOy2l1VEbe9U0SW3/GhBSyIF6ir5L1qSLWka+8BrrLs39eMkMyx2"
    "zv/OSfGZyLe3rm/ccPP+bNAcZv3n88rYDrRAg/vmUnPLZv0zOJt0ASEstIVuB1qehB/p+W"
    "UoH0GdyPgX9P33Ud+u/Ozy4uT85/YV7B25PLM3xmxMCfH907rIzy4iLG/727/MnAfxr/+v"
    "jhLEMwjJPrKLtj2e7yXz3cJ3uVhFYQfrFsF/D6/GgOzDesqcxvAZHGB2a2c/vFjlyLOxOO"
    "Qllb/tRitKgesQP7OnstGFzcTarEvfXibC04D91V9tycmldp0a9T9Vza1lpkjbeg7/3OK2"
    "TkXr0/mqqCIvIsZc5N6TJ9zU+q8hGuPBqaR+Z0fGgWFLk4UseM87VQrt+1TYV+FjRuUXxV"
    "TdEsJboJ46HZAMVDUwoiPvWtLdPnmXMTpq8qEU2cxbnaKROlrTLNfDeTZW4D0LOlni27N1"
    "uuZfzSZq8as1dL5tGTlB6nfHoZppBG78Nr0XzKtamdV23Y2vJp84em197n1cAcHuJfc5z9"
    "DvDv2M1+yf9nRvYPyk6Psv/PQVPyS47Pst8JuET2a2bHzYlRFaCXQ9wNRuWFmDaj9BKjwd"
    "AkVzoqr2ceZ/+fAokB0+/sD3NYdp/2w4FtpwY4j8T9pI9Nz77uVQa4RvSxiH4OOESm4kcg"
    "N2cekLQkuFD8J+DqJnwmgzvhgiMOuQR8SnJiCLoB/s9cgnTDBpfgOzB2De6lH/XxsYE9A9"
    "eawN66EFyn2hOzhGgwmzFv1oXA8K95QlBnOwPvxdwfPrwNno6MSgce528IsRz1+U+Bec3M"
    "8DHAhcmtELj6BEhLX+GMG4hjJZgEr4xBiQ7e9WCiL3RaXoIO4dFBdn4EXjLz0ZCLTI3bdI"
    "n+/nPvOkIoSaejzz2j/AKYTpOLz8HlyKXn+WOU3T+CX4axV+0hhecIwDOGb2XKjU6bigUQ"
    "Pq4VnASn4NVRoEnTGT+7rDdtgAFB+0JaOoa4Ywz6YzjSHzFTlIOovBs/QR4LhuB+ZiB/OF"
    "zgd8b9DIgiHjhER9JK0QaVIh0isF3HtdaPtoluNikoaPJ5+24q8MPDBvr7sOo1KdV3fKri"
    "HERzFfho8444A3dg/YhRkAidf3VfNxDSX3cXrB8XKMFcNX7QBFI0VLCDxFCmmTGE1wcHHA"
    "kUkO+BQD+DKvwAXHZS1QLMw0KsVEUAh4S6eE6y54BcDsBlZeoRoLWwA7mGvpYNAXL8HIcD"
    "sUVEw/pIWIm+NBpV+5QDCLq/ntXEnL+qdo02HTcRhvYeqJ0wFiKgDUJNFLyCyouid5K84F"
    "wt7UPrFWhLe0u1OIi/QAWnFhCgwDEPS47MhZ0usKCj5BV46zN4wgA9nEHccqUY/x6CRgIN"
    "E47KQ9ARandrqApKdb226Cw70v12wqnlGmJuqlkzuFEkvsMQR1Wf7ZPEOBYYJeirgEzKo/"
    "Q4wY5Q813H6dlf7Ps1x29VVI9dAbSq45YR0mNWPmbjxI4Sa+EFq4TE7jW0cIqF11r2nkBx"
    "34jNk/v63XVxrIi+VBRxvCyO+F13IhXJ69m0NSaPn9H9lzByP6FlFtDNWTqY8/06A8ctaZ"
    "m+7KXvNQw5Bir4EzlZM43INKvK4bj0G5aKH9RhEdfbAdDDeK12LngWch6GAUANC8ZWEPU0"
    "93JCl90RjCjIOj1hnII1Rg+N+FYQZwIWJkBN5jzO+ePvw0gG8wFDCv8IZglDETRR3lXg/u"
    "UtTfyTz2XqOuuqpR+9DmPVHtsu2j+AT5EOZA7eGrdiKdJNz+JWnGN4+VdXDVmprsC5C+Ww"
    "JTzxfJWRV44fZsdreeEi16B0TsVzWYx0ToXOqejY+p7OO96dIL+v3nhRCGmLBQvnKkg8X2"
    "2oFiLdsqTteJymK3Vg+d7CE9AnKbSsULfw3ZilMgPBCVeBMnKF0O6m0EHLcHNX6RN6omIh"
    "dZ80J9qtofdyAtsukjC6x0FruGBGT0Dj2Qa1fD7GTS0btm1m5oWZZkfAmCeOt8lNbEw2Bz"
    "QqwpQFLk2iyAspTzOJYdKciWNi8aP3PuS7M+QMly68IbnIPp9vwkdu0ZQrQSAZNM9CC+oh"
    "Z6wDSXfjY7GtV8O+ZdhhXqAgPgvmJDE5XUzqzTHoMwWdNHLBpZDEKs7GgxE5EMtFARuLgr"
    "xeZZ/za3hhAHgeM5j9wkwxWUaSIK0KZgrlVnXQiHMBpPcP9qiz8PvLdG3YB1dmgxi5oEJm"
    "pAp6pxihmfsyTCBwDJrOoOF+mB0bDY2i8z/gyXCfpMgNYS5Y/iUFvh0nFp5GLVzzCWSQ8d"
    "GAJhPVB9MBmUfnbkNjCXNoy29ClF4HPT4wMHbSh7dlPm9ZbhyfIIzgTajcBLSiWaN96kA5"
    "qo4hNreOSYgkzwJiIJnQUEcxbpMKC3IfYeL0oBwn7Lh+IJyTT5MTzEiMB+exkZNtM9c8w5"
    "q76wVH6PqPMvsCOzGqjFlesiORZuyoHY8aDNrxSDpm8anWqB+4+tIPvi3OpSlP1qodmaVz"
    "XrRrpnLAlbE+joHxfUujIBBoa4N5HJavkNZq4PIyzPFrQVUFyAJgijZc2WFvQCGMbKEhBR"
    "Y4olddoNcqyFEuU/zFCdjDqSTPRr+KJ3gVhErl3NPIwwEomxvwTIpFGj6nqfjmkCEtXyGJ"
    "4TH5BB/4+nOeX58O9Yguj6fNYl60m1HHvHTWIKk9jrtCNwgtkvNLI2cV9IKqqPY+8tB6a2"
    "DqaTCFYEZoISyp8RCgpZwGtTXK1g/2XRilHZOVw2XO16pcc9pSoSxuxvVHDL3uc6ydNwzn"
    "pvTGVlrK/A55ngprzzFVuiC/J4eOSnov8yzQjuVkfo+j/A4nR43FxkEK375YGdIAlQClKg"
    "pQUvgKAdSqe8RdJtcGm2g1tsGYMhnVBGa428ZtkF6ODPjXAuWD8fVsWPvgzP9Fdcs9+NgA"
    "mnxQzFaxF6A4tpin3IdeJr7MAVVfm+tnIr9BrmFuygVhwjqU0PvB1+FwjKsgTIfQVe5WOM"
    "BpZrbvay1Oa3EvSM/QWtym0W0JkfsZL0UyFleerKVwYDlT4G9r1gptQmQEhWOU6Uw1SqQH"
    "GAKMdskXmZ40p/BRPENM7TR2TbBjyxELSRqkXxumWpONUy3R88AYqRlAHUJDhwVHsSkpmo"
    "F3LCv/+xC1o7yyST3jWfkyixvNwoTXIWSVgItH63HDpTZ9t/CZ9GCxKz5ajC0vzzmCmEey"
    "q33Mi3pTkJyDdLwt0tnXjV/Fjr04WN5r5qiZ4zPnNpo5vgDm+IbMaye+Z4tDLuD5Wv5IZ0"
    "jLxk2VinrUWgFkUaSCQEwYMTClizCY5aG5CsbNNrFBmbPXxtUBWamwFWE0PB4Zyyicez6C"
    "UZvNCE+V6kjiIDQujRbZbMDpJVYvsd1bBJi003yKbRq+WAh0MzN6M2GLDEkhK5Ba2HIh0k"
    "0Un9XWnP+78pzbS7RY+ra4hATboJaO/IWbWgltq2LSAishk9qC4CIFlG5p+W/G+lIfrDfA"
    "y2gCs1fI0j2/koTXNVHMmUpdDxaLggpv4+JP44nEbalBVAbxQaKTfQya52ie02mek/2rsE"
    "Tn7bu5Pm+e5ajWy9KVslpbKevEexvZc6HTLj9Vy3Fsz3JxK/WAK+gk4TwYuaOp0ZrLZBHA"
    "rTCZjR1AWix1uMB9S5j9AMnVp+Klkt3dUWH/lNroqpeJxiPSRDW30NyijdxCuym2iW4cri"
    "IHWQsUx+l6poyzUFwjXoe45nqb3TIDBY51hyIe0ouF7fvSkQvEulW2ajw6OiwGKP6jbkhe"
    "nJ+8fy+YUyOEn0x5F0tWTn/ntTNrYicrJeN/KbG7b723RIGLwXsEvFvYr7Y1ylztNqBew7"
    "0/PbUNP+XI6/3zWvWxP4+CMK3NqOtXPjmVuTRvv8OZ1M2NOxuZR6cNptGpdBadVi2MHr7V"
    "KgtYFaxJcvZZletINZ1dk9Abj9TFpIqQym5jItHdMathi0rRurbn3ytXP65I7Q668RND1x"
    "KO9CnLAq/fMJ1rU8uXItp6nW3SYRIDn/YKi3FyBVCJ5ZWmwJprJnIY3B1kO0zP2IRVmmcg"
    "yF6tN08zdTE/0zRcJ4zQqxzG+GB5L8lE1nDVwaXZtmbbL5Nt34SrSInD5O13t/qa7eEtf6"
    "08lKy9a69EultGyQ1jud6+vULZF4pjXrwltsJAuQAVL6wnyNbw7XOiJ/5E1EYR2660qOXa"
    "uefuBjTe1UZt/fL2gnzKekHgiUjlRG1BAx3zsNZsoneA0zvAbW+p27E7bt0IBx3a0BxjLy"
    "UMWIVVpBtQbIdEY2sW5g0qYjsNFnn+ZvoFcj2boKKwaLFSHYF2G155HkrMEETzaWBH93Vg"
    "5nLVz/2eam2tg7Puc8fjDI7UFLXTdx9OPv0mHqp5e7xLxXWUXah3+tvl2YkQ4YWnllrBSn"
    "VysG6FXRFcxIkq8vmUleoImk8zq6rHO1XlOgLvtmfWW2ExZjmMeftOwjdqkus8kuc6j8wq"
    "fChIvMQTGQ7/fvHxg8wVUMpUYPw1SJ/vd9dzkr7he3HyRytBrQERP3X9J1/9uitrE75A9Z"
    "OPb8IvlmNn/bTsWai8t7b4AtrMWPHD2LEVL0PPV9apKpIa2Ip5PAVG0XQFRLo5026DVWWg"
    "UKvvGnAykp1EdTO1OjhIY+/fohm1xk7FiHXL6bVjK9XSvvdDWzBY5fwAiGh60IAezMMIO7"
    "pUIAYiGuIGEEf2F+vPOO2jAsZQRoPcAORZqO6RKWX0LFzrj8HK/3UUrpaKzIGX1MyBOAsi"
    "OyAdU3IZMFIdgVInmeok03b5A19clWEaZfQ+vO7JY5Dw2X6T+COfNtxmbmR9RFHagyIMSR"
    "gsRBsojeVSpktxQ08czq2ji3R0USeGsI4u2mkhoKfjE89ZKWsJnTiJnBvvTkYnwNlaOmGT"
    "dk9FJ9AdIuNJkwlNJjSZ0GRCk4mWYlzM1E2ng0Kgm9PA5msWh/gyiuHJUEZbGoWWxgB9UY"
    "YVymhYdeT3LiK/dVyyjkvuxDev45J1xkdHMj505PejIr+7lX7YiTjZ9NNNLNVhyQjpsVlo"
    "S3FgL+ObUEDt5SFbVTkdttV/OGwL60PrgF2V02A3ATtMvEfsICAU106aOtOVjkWSQ6hjkV"
    "6w8/CXCM1Jr8XuQ3K+38SBuCyaNqs7aoNSlXbjHZxoacpDsjvUBNSvhJtYjeD1ptUr0f01"
    "HXKNcbXuJW0Ky3qCW4t2niJ7WA1Al8AW3+OBsYdXgT7cFdM5MLISmgx4NVVHNVhSsB5Rc7"
    "Rtns6t+5e3ZZyTO5PFxg85oZQYPdYhkmstI73/ma+C7M0as5XnJ14QH+Db/q3Xbn7ZkmXl"
    "lyjEaXWn6cVWS9G6wjaoXViWpKk1y9o+4UYgeprY+jQx80IVYz5t3hFLya6t+MtUGQ/XMD"
    "uzctrsLDc7z70oTiQuqLoEbijVkcG7A4eeb68BJiOksSzKjNh3ayjtUEqr7C1V2c+9KAqj"
    "01C4U3Z5spZTLbJm1ixsuFv2VviU3uph0yO0jlol4S0KLBQ40f0SY6NECQTCa/KCJ5ghno"
    "AY6PT3rRnxMUyrGEWqRKEqp7mCNvHvtMBzur56ytXeGLkdxlgUS2DLQixawsHe+KFze7YI"
    "//REJAycrWVhDm5nIdxQwWMygjuG1e7ZRezmzNlpueEXswEZv8mX6Rj/ZQBzPtjSjJj/zd"
    "xSD64CTyDqpfjub4azipNwQZ40XePI7mFiF8ezejrhrh5xcu9nn3PiLZB1i+65DTykjFnv"
    "uiGaUh7mvgXkTclCIbDDXXAd345jz3mEg2HbiSvFgFVAEsp0MwFo8/HAy3QNsrLuK3zOrF"
    "DH2NbGdueqzLVKXhhe9GXrAG3iUr+kl5JSqexkAyaFPxGV0BMEIhcoASDLvQuYAWxEwiWm"
    "32X/zJlYjEvko+vIXhxkVxiyJ8v2JOBBsD+sycVMHIKYiRGkITyZQQaI5hiAkAnS+ZGxly"
    "1osqiSl4lDPTkD062mZ5qedYGeaVqxNq3IUFC1KDJC3eS2W7Enrpa45DNyU6hWolIB0rHI"
    "C+5uPA7aMxidcLH0kdhHU2crZOR0PlZrCG5mCbzIkmIvUJIQLDimK2hVS3mJHkNyba2YSG"
    "hn7gtx5qYMO1CfIICUnh6qqUH4EVUBBVIa0Moilmnkysy+Ivbi+X1LlrBfYxS9Dx076yS3"
    "dIGztUsWdr9bftlQL1TPfqEq33bjgM5CYocff7Ta2Hc/bfDZT6Vf/ZQPig2uVzi/17kJYy"
    "TYtKR2gRJI64WKd2r9OwyQFc7nKY22Fl6wSkSbIErnhpor7E5/HU5bpMHmiKg6CnOZTvpl"
    "NrMtSUsW/H+EnoPO5nPkCMOM4enaJf8ON7RQ1nIL2mnNxgTaar9lq33b0uGehe1U1wfePD"
    "sFWn4xYzUdq6VENwfps1qULpwb5K585F7asTBagG1QuzDFeVMrSdsqRw2YsOwCAn5qWO/A"
    "BWcnBnBvk0bHD0Qx7h1gThQZr4yDWbiY7b8G/nMaCDkQ+8nzIgowZNKoCjB3htUYaCGIKa"
    "y9gGhYwCeUDtyoLo5AI/MY64QmI+uRkZ0WgHzyWX3zIYmazGky1zEy94SbPbyUXDvVcvq6"
    "lL7eCxWM1k3UH4xWgXJiYimzrRm0s76almhyP6Zv9yKdhwlOnB4HT9dqcddpQysmLdeN/K"
    "bRx1CFYDg/CD+eS1LG8lBocmgMpGe0qB4fmEzz2RjVBXHhzVQtodlmUF/Ku70H5cFj2TAu"
    "GtydK8g3nvQFvesb4icaD5pEkWtMVTH9HHwOrkg011WuZV6VVOUKFGc0Z+B2QGGF3WBBoh"
    "1HZfdztRWcnbKPbXDP5IDum0RFpxmRArUYpmuSx58D2Ea8Bk1+h+XFRaimKGVy8KmgLWEO"
    "jg/guNqn2KPqYKDNaFIod8EJ11FGGJVPxnY0FRsNhmb+ErI3i674opa09OUE9JWmnI4N7l"
    "kOwVAk3TuWjCj6+pl3QfvazzEktzxI+4aiO89BBz+enJ9Zb89+OPn1/eXFVU2SRN1m0HhG"
    "1r4X7XvR6rpW1xl0rxWzK/L23Rygm7fQqe/G9Mh9mNaLpCqrlbQUR2022vqnnpEdHl15te"
    "dCQJd77mS55xMfRcI4IXKiVoW3cRMV3X1Q8mImBXgkIe9MwjEoVk+L2PNnIc0W6CCNy+4T"
    "dcI8JDejCdEyLfkBBXVQUVDzeOS+4aSQ7r8Wq+QaKgFURP9htPsRp9IxWhSs+AMVRapVy7"
    "ZEmJVQUDsA54Iu1OGrLOXximqpA+MK7+6Tfn24utoV5yA3oT4IM+MZWwvp0RH5P7SycO+O"
    "nlbVx6niS1Vsub4Ig+fxO9D64bb1w7YkOTwjyznrLXfVsppo+27qMpuJIXuy7TqfHL8NZ4"
    "S4KLE9X6AJ1uymUopohr3+hn3af6vuv1WtAfEEpR+GT72O61K8u1y8sx0jVAEGQhrdOnSB"
    "3qKGcEVQo1yHsuvFCy+OlQsWMHI6E7RdBrTzVdYzsREtO9l/0JBmLfLU00bWNFoleQgVf2"
    "iQYew4LmcpYu0uwNww4wwdo+Kqg9nsNR+VYPKXhWEOnOuddhBBt/4IXJUL0piQZ3ShMYU0"
    "mq9lphoPhHEwGtHHIqpNSDuknl00IT2PJVzbkHrKNqSWrNbvveA2duzgje3cCFdstkHtqu"
    "3TppZTtFVPQ2T2RgDzN+M8IUeIUwDx7h7gCaGT9XF1ys6jFVkHC3c7WEIYzvtsih2MXKOe"
    "Erg/NWlFD5lcr+iiQj1FggUqD8CLb+zR5PCBvpCzNWGtGucN4vw52JMwBnkHBLeRN6bBnk"
    "yApw3icXOHnsH0Cv86AKCHHgMCe1SfgDovm1JpG94I0kCTGQHlaRo+C3c+mcvp0jIK7zyX"
    "2Bxz47neaWQHrAkC33RlhzLdXN03H6X1sjxETciRnBvx7jW1LVo6vTvL5p2TPrpDvsLsV7"
    "TvmL6zMadFhOyYpl81dUgCkTY5JPENO+WQ/Lr00tPKtnZWTod6tDNJstAib2xhcCVzvqGS"
    "mTZV2WpQlL4Gc9CGYrKa56ARai61D8rUIkiB2dw0SKE5wyaNyqMBb+BKDGkWbEJjxE64RM"
    "b3xudejHzkpIP+c0+S5qghedg+qyvwaRPtszDR6oSw572yXuTbZtSsrhdwa42HV1ilnTiI"
    "hRFsfyYNbT/mrUYqSwW49hCsQzAV3F7XZ0dMg3AJbJImDy2jbAg93G5uBqThYkoWPfRaFQ"
    "lqtBuJTb36Rez8RTDJ6ICa5NhC6zu8+qCKkQltr6PdGnAFJQEgBrDkIaykwDw1fCB4H2qX"
    "fmxdwbZQhZex64HeTab3+NAsJqMUayMqNs1CYJepz77/CNvRVnMG0NcERYEtMGvWj0ggts"
    "MhWcwJLRuRLWGvH/Gs/DO6F7HW4lwtWyXz+i26V6GpYudvwUsktg5zvSTQ8QAW7CFGlQk0"
    "rbglUTEh5TmGiY4clcsX2+9q6RGiay4hVE2SaGmFI6bqD9zVeFo+hTQmsLyGiDdROkDzLv"
    "9bTGD1K2rRK4LUVlBLmm5x3eBaTMBGs8iAvjSk1AB3YoI/yQnI8HnSO+1zrSgypBWk2nyc"
    "C28HnUAKrpRGfIeirDqgtjFqG2MHVYcS33wgc/DW5xQCsY7hu4mkwi9Rym2Qa7noVjQuAz"
    "u6F8NWEaxy2nuaO9E+8OrGGXUWF6Q2VQNO3304+fSbuFbxqcC5fPrb5dlJtVCSHafs31pz"
    "gPLSL3Cc6nTOZ+1GOEGR59yI1DB6plYJs8s2T7IRqmZE6zEi6YQot0bJZ8GORNltpd4m/j"
    "QUQKTNuwngcDBoEiI7GMhjZPE5btOWBImqK8gD74DIUwXebY0IPY+qet/+H5xHK8o="
)
